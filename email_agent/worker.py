"""Background email worker for the regulatory ingestion pipeline."""

import argparse
import time
from pathlib import Path

from regulatory_ingest.models import MatterNotFound, PipelineError
from regulatory_ingest.pipeline import run_pipeline

from .mailbox import ImapSmtpMailbox, IncomingMessage, MailboxSettings
from .gemini_parser import extract_request
from .parser import AgentRequest, RequestParseError


def process_message(
    mailbox: ImapSmtpMailbox,
    message: IncomingMessage,
    output_dir: Path,
    database_path: Path,
    limit: int,
    headed: bool,
) -> None:
    attachment = None
    try:
        request = extract_request(message.subject, message.body)
        result = run_pipeline(
            matter_number=request.matter_number,
            document_type=request.document_type,
            output_dir=output_dir,
            database_path=database_path,
            limit=limit,
            headless=not headed,
        )
        body = format_success(request, result)
        attachment = Path(result["zip_path"])
    except RequestParseError as error:
        body = f"Hi,\n\nI could not process your request: {error}\n"
    except MatterNotFound as error:
        body = f"Hi,\n\nI could not find that matter: {error}\n"
    except PipelineError as error:
        body = f"Hi,\n\nI could not process your request: {error}\n"
    except Exception as error:
        body = f"Hi,\n\nThe request failed unexpectedly: {error}\n"

    mailbox.send_reply(message, body, attachment)
    mailbox.mark_processed(message)


def format_success(request: AgentRequest, result: dict[str, object]) -> str:
    matter = result["matter"]
    counts = result["category_counts"]
    downloaded = result["downloaded_count"]
    requested_count = counts[request.document_type]
    return (
        "Hi,\n\n"
        f"{request.matter_number} is about {matter['title']}. "
        f"It relates to {matter['category']} within the {matter['type']} category. "
        f"The matter had an initial filing on {matter['date_received']} and "
        f"a final filing on {matter['date_final_submission']}.\n\n"
        f"I found {counts['Exhibits']} Exhibits, {counts['Key Documents']} Key Documents, "
        f"{counts['Other Documents']} Other Documents, {counts['Transcripts']} Transcripts, "
        f"and {counts['Recordings']} Recordings. "
        f"I downloaded {downloaded} out of {requested_count} {request.document_type} "
        "and attached the ZIP.\n"
    )


def run_worker(
    mailbox: ImapSmtpMailbox,
    output_dir: Path,
    database_path: Path,
    limit: int,
    headed: bool,
    poll_seconds: int,
    once: bool,
) -> None:
    while True:
        for message in mailbox.unread_messages():
            process_message(
                mailbox, message, output_dir, database_path, limit, headed
            )
        if once:
            return
        time.sleep(poll_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Connect to the configured mailbox and send replies",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process current unread messages once, then exit",
    )
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"))
    parser.add_argument("--db", type=Path, default=Path("regulatory_ingest.db"))
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.send:
        print("Email agent is disabled. Re-run with --send when mailbox testing is approved.")
        return

    mailbox = ImapSmtpMailbox(MailboxSettings.from_environment())
    try:
        run_worker(
            mailbox,
            args.output_dir,
            args.db,
            args.limit,
            args.headed,
            args.poll_seconds,
            args.once,
        )
    finally:
        mailbox.close()


if __name__ == "__main__":
    main()
