"""Playwright interaction with the Nova Scotia UARB portal."""

import re
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .models import DocumentCandidate, DocumentRecord, MatterNotFound


START_URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
MATTER_NUMBER_PATTERN = re.compile(r"M\d{5}")
MATTER_FIELD_SELECTOR = "#b0p0o254i0i0r1"
MATTER_SEARCH_BUTTON_SELECTOR = "#b0p0o258i0i0r1"
MATTER_METADATA_SELECTORS = {
    "status": "#b0p0o289i0i0r1",
    "type": "#b0p0o298i0i0r1",
    "category": "#b0p0o287i0i0r1",
    "date_received": "#b0p0o292i0i0r1",
    "date_final_submission": "#b0p0o294i0i0r1",
    "outcome": "#b0p0o295i0i0r1",
}
DOCUMENT_TYPES = (
    "Exhibits",
    "Key Documents",
    "Other Documents",
    "Transcripts",
    "Recordings",
)
DATE_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")
PDF_PATTERN = re.compile(r"\.pdf$", re.IGNORECASE)


def search_matter(page: Page, matter_number: str) -> tuple[dict[str, str], dict[str, int]]:
    page.goto(START_URL, wait_until="commit", timeout=60_000)
    fill_matter_number(page, matter_number)
    page.locator(MATTER_SEARCH_BUTTON_SELECTOR).click()
    wait_for_matter_result(page)
    return extract_matter_metadata(page, matter_number), extract_category_counts(page)


def fill_matter_number(page: Page, matter_number: str) -> None:
    """Fill the portal's FileMaker contenteditable matter-number widget."""
    field = page.locator(MATTER_FIELD_SELECTOR)
    field.wait_for(state="visible", timeout=60_000)
    field.click()
    page.wait_for_function(
        "selector => document.querySelector(selector + ' .text')?.isContentEditable",
        arg=MATTER_FIELD_SELECTOR,
        timeout=30_000,
    )
    text = field.locator(".text")
    text.evaluate("element => element.focus()")
    page.keyboard.type(matter_number)
    page.wait_for_timeout(1_000)


def wait_for_matter_result(page: Page) -> None:
    page.wait_for_function(
        """
        () => {
            const text = document.body.innerText;
            return text.includes('No Records Found') || /Exhibits\\s*-\\s*\\d+/.test(text);
        }
        """,
        timeout=60_000,
    )
    if page.get_by_text("No Records Found", exact=True).count():
        raise MatterNotFound("The portal could not find this matter")


def extract_category_counts(page: Page) -> dict[str, int]:
    body = page.locator("body").inner_text()
    return {
        document_type: int(match.group(1))
        if (match := re.search(rf"{re.escape(document_type)}\s*-\s*(\d+)", body))
        else 0
        for document_type in DOCUMENT_TYPES
    }


def extract_matter_metadata(page: Page, matter_number: str) -> dict[str, str]:
    text_items = [
        value.strip()
        for value in page.locator(".fm-text-character").all_inner_texts()
        if value.strip()
    ]
    excluded = set(DOCUMENT_TYPES) | {
        "Hearings",
        "Related Matters",
        "Back to Search Results",
        "Public Documents Database",
        "Search",
        "More Search Options",
        "Tribunal Home",
    }
    title_candidates = [
        value
        for value in text_items
        if value not in excluded and len(value) > 20 and " - " in value
    ]
    metadata = {
        "matter_number": matter_number,
        "title": max(title_candidates, key=len, default=""),
    }
    for field, selector in MATTER_METADATA_SELECTORS.items():
        metadata[field] = text_from_selector(page, selector)
    return metadata


def text_from_selector(page: Page, selector: str) -> str:
    locator = page.locator(selector)
    return locator.first.inner_text().strip() if locator.count() else ""


def open_document_type(page: Page, document_type: str, count: int) -> None:
    tab = page.get_by_text(
        re.compile(rf"^{re.escape(document_type)}\s*-\s*\d+"), exact=False
    ).first
    tab.wait_for(state="visible", timeout=60_000)
    tab.click()
    if not count:
        page.wait_for_timeout(500)
        return

    pdf_only = page.get_by_text("PDF Only", exact=True)
    pdf_only.wait_for(state="visible", timeout=60_000)
    pdf_only.click()
    page.get_by_role("button", name="GO GET IT").first.wait_for(
        state="visible", timeout=60_000
    )
    page.wait_for_timeout(1_000)


def candidate_from_button(
    button, document_type: str, display_order: int
) -> DocumentCandidate:
    row = button.locator("xpath=ancestor::tr")
    lines = [line.strip() for line in row.inner_text().splitlines() if line.strip()]
    document_number = lines[0] if lines else f"document-{display_order}"
    extension = next((line for line in lines if line.startswith(".")), ".pdf")
    date_filed = next(
        (line for line in lines if DATE_PATTERN.fullmatch(line)), ""
    )
    security = next(
        (line for line in lines if line.casefold() in {"public", "confidential"}),
        "",
    )
    ignored = {"Public", "Confidential", "Preview", "GO GET IT", extension}
    title = next(
        (
            line
            for line in lines[1:]
            if line not in ignored and not DATE_PATTERN.fullmatch(line)
        ),
        "",
    )
    return DocumentCandidate(
        document_type=document_type,
        display_order=display_order,
        document_number=document_number,
        title=title,
        security=security,
        extension=extension,
        date_filed=date_filed,
        row_key=f"{document_number}|{title}",
    )


def record_from_candidate(candidate: DocumentCandidate) -> DocumentRecord:
    return DocumentRecord(
        document_type=candidate.document_type,
        display_order=candidate.display_order,
        document_number=candidate.document_number,
        title=candidate.title,
        security=candidate.security,
        extension=candidate.extension,
        date_filed=candidate.date_filed,
    )


def next_visible_candidate(
    page: Page,
    document_type: str,
    display_order: int,
    seen_rows: set[str],
):
    buttons = page.get_by_role("button", name="GO GET IT")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if not button.is_visible():
            continue
        candidate = candidate_from_button(button, document_type, display_order)
        if candidate.row_key not in seen_rows:
            return candidate, button
    return None, None


def scroll_document_list(page: Page) -> bool:
    """Scroll the portal's virtualized document grid to reveal more rows."""
    scrollers = page.locator(".v-grid-scroller")
    for index in range(scrollers.count()):
        scroller = scrollers.nth(index)
        metrics = scroller.evaluate(
            "element => ({"
            "scrollHeight: element.scrollHeight, "
            "clientHeight: element.clientHeight, "
            "scrollTop: element.scrollTop"
            "})"
        )
        if metrics["clientHeight"] <= 0 or metrics["scrollHeight"] <= metrics["clientHeight"]:
            continue
        before = metrics["scrollTop"]
        scroller.evaluate(
            "element => element.scrollTop += Math.max(element.clientHeight - 40, 1)"
        )
        page.wait_for_timeout(750)
        return scroller.evaluate("element => element.scrollTop") > before
    return False


def download_from_confirmation_dialog(
    page: Page,
    destination_dir: Path,
    fallback_name: str,
) -> tuple[Path | None, str | None]:
    """Click the dialog's PDF button and return either a path or an error."""
    try:
        page.get_by_text("Download Files", exact=True).wait_for(
            state="visible", timeout=60_000
        )
        pdf_button = page.get_by_role("button", name=PDF_PATTERN)
        pdf_button.first.wait_for(state="visible", timeout=60_000)
        with page.expect_download(timeout=60_000) as download_info:
            pdf_button.first.click()
        download = download_info.value
        filename = Path(download.suggested_filename).name or fallback_name
        destination = destination_dir / filename
        download.save_as(destination)
        if destination.read_bytes()[:5] != b"%PDF-":
            destination.unlink(missing_ok=True)
            return None, f"Downloaded file is not a PDF: {filename}"
        return destination, None
    except Exception as error:
        return None, str(error)
    finally:
        close_download_dialog(page)


def close_download_dialog(page: Page) -> None:
    close_button = page.get_by_role("button", name="Close")
    if close_button.count() and close_button.first.is_visible():
        close_button.first.click()
        try:
            page.get_by_text("Download Files", exact=True).wait_for(
                state="hidden", timeout=10_000
            )
        except PlaywrightTimeoutError:
            pass
