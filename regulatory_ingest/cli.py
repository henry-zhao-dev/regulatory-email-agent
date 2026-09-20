"""Command-line interface for the regulatory filing ingestion pipeline."""

import argparse
import json
from pathlib import Path

from .models import MatterNotFound, PipelineError
from .pipeline import run_pipeline
from .portal import DOCUMENT_TYPES


def normalize_document_type(value: str) -> str:
    normalized = value.strip().casefold()
    for document_type in DOCUMENT_TYPES:
        if document_type.casefold() == normalized:
            return document_type
    choices = ", ".join(DOCUMENT_TYPES)
    raise PipelineError(f"Unknown document type: {value!r}. Choose: {choices}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matter_number", help="Matter number, for example M12205")
    parser.add_argument(
        "--type",
        dest="document_type",
        required=True,
        help=f"Document category: {', '.join(DOCUMENT_TYPES)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of top-to-bottom PDFs to fetch, from 1 to 10",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("downloads"),
        help="Directory for cached files, manifests, and ZIP files",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("regulatory_ingest.db"),
        help="SQLite cache path",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser while it runs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_pipeline(
            matter_number=args.matter_number,
            document_type=normalize_document_type(args.document_type),
            output_dir=args.output_dir,
            database_path=args.db,
            limit=args.limit,
            headless=not args.headed,
        )
        print(json.dumps(result, indent=2))
    except MatterNotFound as error:
        print(json.dumps({"status": "matter_not_found", "error": str(error)}, indent=2))
        raise SystemExit(2) from error
    except PipelineError as error:
        print(json.dumps({"status": "invalid_request", "error": str(error)}, indent=2))
        raise SystemExit(2) from error
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
