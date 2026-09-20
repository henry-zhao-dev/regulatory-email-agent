"""Minimal SQLite catalog and download cache."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import DocumentCandidate, DocumentRecord


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initialize_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS matters (
            matter_number TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            date_received TEXT NOT NULL,
            date_final_submission TEXT NOT NULL,
            outcome TEXT NOT NULL,
            category_counts TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            matter_number TEXT NOT NULL,
            document_type TEXT NOT NULL,
            display_order INTEGER NOT NULL,
            document_number TEXT NOT NULL,
            title TEXT NOT NULL,
            security TEXT NOT NULL,
            extension TEXT NOT NULL,
            date_filed TEXT NOT NULL,
            filename TEXT,
            local_path TEXT,
            download_status TEXT NOT NULL,
            download_error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (matter_number, document_type, display_order)
        );
        """
    )
    connection.commit()
    return connection


def save_matter(
    connection: sqlite3.Connection,
    matter_number: str,
    metadata: dict[str, str],
    category_counts: dict[str, int],
) -> None:
    connection.execute(
        """
        INSERT INTO matters (
            matter_number, title, status, type, category, date_received,
            date_final_submission, outcome, category_counts, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(matter_number) DO UPDATE SET
            title = excluded.title,
            status = excluded.status,
            type = excluded.type,
            category = excluded.category,
            date_received = excluded.date_received,
            date_final_submission = excluded.date_final_submission,
            outcome = excluded.outcome,
            category_counts = excluded.category_counts,
            updated_at = excluded.updated_at
        """,
        (
            matter_number,
            metadata["title"],
            metadata["status"],
            metadata["type"],
            metadata["category"],
            metadata["date_received"],
            metadata["date_final_submission"],
            metadata["outcome"],
            json.dumps(category_counts, sort_keys=True),
            now_iso(),
        ),
    )
    connection.commit()


def cached_document(
    connection: sqlite3.Connection,
    matter_number: str,
    candidate: DocumentCandidate,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM documents
        WHERE matter_number = ?
          AND document_type = ?
          AND display_order = ?
        """,
        (matter_number, candidate.document_type, candidate.display_order),
    ).fetchone()


def save_document(
    connection: sqlite3.Connection,
    matter_number: str,
    record: DocumentRecord,
) -> None:
    connection.execute(
        """
        INSERT INTO documents (
            matter_number, document_type, display_order, document_number,
            title, security, extension, date_filed, filename, local_path,
            download_status, download_error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(matter_number, document_type, display_order) DO UPDATE SET
            document_number = excluded.document_number,
            title = excluded.title,
            security = excluded.security,
            extension = excluded.extension,
            date_filed = excluded.date_filed,
            filename = excluded.filename,
            local_path = excluded.local_path,
            download_status = excluded.download_status,
            download_error = excluded.download_error,
            updated_at = excluded.updated_at
        """,
        (
            matter_number,
            record.document_type,
            record.display_order,
            record.document_number,
            record.title,
            record.security,
            record.extension,
            record.date_filed,
            record.filename,
            record.local_path,
            record.status,
            record.error,
            now_iso(),
        ),
    )
    connection.commit()
