"""Orchestration for searching, downloading, caching, and packaging."""

import json
import re
import zipfile
from dataclasses import asdict
from pathlib import Path

from playwright.sync_api import sync_playwright

from .database import cached_document, initialize_database, save_document, save_matter
from .models import DocumentRecord, PipelineError
from .portal import (
    MATTER_NUMBER_PATTERN,
    close_download_dialog,
    download_from_confirmation_dialog,
    next_visible_candidate,
    open_document_type,
    record_from_candidate,
    scroll_document_list,
    search_matter,
)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def run_pipeline(
    matter_number: str,
    document_type: str,
    output_dir: Path,
    database_path: Path,
    limit: int,
    headless: bool,
) -> dict[str, object]:
    validate_request(matter_number, limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    category_dir = output_dir / matter_number / slugify(document_type)
    category_dir.mkdir(parents=True, exist_ok=True)
    connection = initialize_database(database_path)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            try:
                metadata, category_counts = search_matter(page, matter_number)
                save_matter(connection, matter_number, metadata, category_counts)
                requested_count = category_counts[document_type]
                records = download_documents(
                    page,
                    connection,
                    matter_number,
                    document_type,
                    requested_count,
                    limit,
                    category_dir,
                )
            finally:
                context.close()
                browser.close()
    finally:
        connection.close()

    zip_path, downloaded_count, failed_count = create_package(
        output_dir,
        category_dir,
        metadata,
        category_counts,
        document_type,
        limit,
        records,
    )
    status = "no_files" if requested_count == 0 or not records else "success"
    if failed_count:
        status = "partial"
    return {
        "status": status,
        "matter_number": matter_number,
        "document_type": document_type,
        "matter": metadata,
        "category_counts": category_counts,
        "requested_limit": limit,
        "selected_count": len(records),
        "downloaded_count": downloaded_count,
        "failed_count": failed_count,
        "zip_path": str(zip_path),
        "database_path": str(database_path),
    }


def validate_request(matter_number: str, limit: int) -> None:
    if not MATTER_NUMBER_PATTERN.fullmatch(matter_number):
        raise PipelineError("Matter number must have the format M12205")
    if not 1 <= limit <= 10:
        raise PipelineError("Limit must be between 1 and 10")


def download_documents(
    page,
    connection,
    matter_number: str,
    document_type: str,
    requested_count: int,
    limit: int,
    category_dir: Path,
) -> list[DocumentRecord]:
    open_document_type(page, document_type, requested_count)
    records: list[DocumentRecord] = []
    seen_rows: set[str] = set()
    next_display_order = 1

    while len(records) < min(limit, requested_count):
        candidate, button = next_visible_candidate(
            page, document_type, next_display_order, seen_rows
        )
        if candidate is None or button is None:
            if not scroll_document_list(page):
                break
            continue

        seen_rows.add(candidate.row_key)
        next_display_order += 1
        record = record_from_candidate(candidate)
        cached = cached_document(connection, matter_number, candidate)
        save_document(connection, matter_number, record)

        if use_cached_download(cached, record):
            records.append(record)
            save_document(connection, matter_number, record)
            continue

        try:
            button.click()
            saved_path, error = download_from_confirmation_dialog(
                page, category_dir, f"{candidate.display_order:02d}.pdf"
            )
            if saved_path:
                record.status = "downloaded"
                record.filename = saved_path.name
                record.local_path = str(saved_path)
            else:
                record.status = "failed"
                record.error = error or "Unknown download error"
        except Exception as error:
            record.status = "failed"
            record.error = str(error)
            close_download_dialog(page)

        save_document(connection, matter_number, record)
        records.append(record)
    return records


def use_cached_download(cached, record: DocumentRecord) -> bool:
    if not (
        cached
        and cached["download_status"] == "downloaded"
        and cached["local_path"]
    ):
        return False
    cached_path = Path(cached["local_path"])
    if not cached_path.exists():
        return False
    record.status = "downloaded"
    record.filename = cached_path.name
    record.local_path = str(cached_path)
    return True


def create_package(
    output_dir: Path,
    category_dir: Path,
    metadata: dict[str, str],
    category_counts: dict[str, int],
    document_type: str,
    limit: int,
    records: list[DocumentRecord],
) -> tuple[Path, int, int]:
    downloaded = [record for record in records if record.status == "downloaded"]
    failed = [record for record in records if record.status == "failed"]
    manifest = {
        "matter": metadata,
        "category_counts": category_counts,
        "requested_document_type": document_type,
        "requested_limit": limit,
        "selected_count": len(records),
        "downloaded_count": len(downloaded),
        "failed_count": len(failed),
        "documents": [asdict(record) for record in records],
    }
    manifest_path = category_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    zip_path = output_dir / f"{metadata['matter_number']}-{slugify(document_type)}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for record in downloaded:
            archive.write(record.local_path, arcname=record.filename)
        archive.write(manifest_path, arcname="manifest.json")
    return zip_path, len(downloaded), len(failed)
