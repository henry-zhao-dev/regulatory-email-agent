# Regulatory Email Agent

A small Python service for collecting public regulatory filing documents.
It accepts a matter number and document category, downloads up to a configurable
number of PDFs, records metadata and download status in SQLite, and packages
the available files into a ZIP archive.

The project has two independent entry points:

- `regulatory-ingest` is the deterministic command-line ingestion pipeline.
- `regulatory-email-agent` is an optional IMAP/SMTP adapter that parses an
  incoming request, runs the pipeline, and replies with a summary and ZIP.

The email adapter uses deterministic text parsing, so an LLM API key is not
required. The portal interaction is isolated from the email code and can be
extended independently.

## Setup

```bash
poetry install
poetry run playwright install chromium chromium-headless-shell
```

## Run the pipeline

```bash
poetry run regulatory-ingest M12205 \
  --type "Other Documents" \
  --limit 10
```

Supported document categories are `Exhibits`, `Key Documents`, `Other
Documents`, `Transcripts`, and `Recordings`. The ZIP archive and downloaded
files are written under `downloads/`; the SQLite catalog defaults to
`regulatory_ingest.db`.

## Run the email adapter

Configure the mailbox variables described in [.env.example](.env.example) in
the process environment, then run:

```bash
poetry run regulatory-email-agent --send --once --limit 10
```

The worker processes unread messages and replies to the original sender. Omit
`--once` to poll continuously. The `--send` flag is required before the worker
will connect to a mailbox or send messages.

Requests should contain a matter number such as `M12205` and one supported
document category, for example:

```text
Please send me Other Documents from M12205.
```
