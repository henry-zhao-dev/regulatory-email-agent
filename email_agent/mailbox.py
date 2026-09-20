"""Small IMAP/SMTP mailbox adapter.

This module is intentionally isolated from the ingestion pipeline. It is not
used by the CLI unless the email agent is explicitly started with ``--send``.
"""

import imaplib
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import parseaddr
from pathlib import Path


@dataclass(frozen=True)
class IncomingMessage:
    uid: str
    sender: str
    subject: str
    body: str
    message_id: str


@dataclass(frozen=True)
class MailboxSettings:
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    from_address: str
    folder: str = "INBOX"

    @classmethod
    def from_environment(cls) -> "MailboxSettings":
        def required(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        return cls(
            imap_host=required("EMAIL_IMAP_HOST"),
            imap_port=int(os.environ.get("EMAIL_IMAP_PORT", "993")),
            smtp_host=required("EMAIL_SMTP_HOST"),
            smtp_port=int(os.environ.get("EMAIL_SMTP_PORT", "587")),
            username=required("EMAIL_USERNAME"),
            password=required("EMAIL_PASSWORD"),
            from_address=os.environ.get("EMAIL_FROM", required("EMAIL_USERNAME")),
            folder=os.environ.get("EMAIL_FOLDER", "INBOX"),
        )


class ImapSmtpMailbox:
    """Receive unread messages over IMAP and send replies over SMTP."""

    def __init__(self, settings: MailboxSettings):
        self.settings = settings
        self.connection = imaplib.IMAP4_SSL(
            settings.imap_host, settings.imap_port
        )
        self.connection.login(settings.username, settings.password)

    def unread_messages(self) -> list[IncomingMessage]:
        self.connection.select(self.settings.folder)
        status, data = self.connection.uid("search", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []

        messages = []
        for uid in data[0].split():
            status, fetched = self.connection.uid("fetch", uid, "(RFC822)")
            if status != "OK":
                continue
            raw = next(
                (part[1] for part in fetched if isinstance(part, tuple)),
                None,
            )
            if raw is None:
                continue
            messages.append(self._parse_message(uid.decode(), raw))
        return messages

    def send_reply(
        self,
        incoming: IncomingMessage,
        body: str,
        attachment: Path | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = self.settings.from_address
        message["To"] = incoming.sender
        message["Subject"] = f"Re: {incoming.subject or 'Regulatory filing request'}"
        if incoming.message_id:
            message["In-Reply-To"] = incoming.message_id
            message["References"] = incoming.message_id
        message.set_content(body)

        if attachment:
            message.add_attachment(
                attachment.read_bytes(),
                maintype="application",
                subtype="zip",
                filename=attachment.name,
            )

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.settings.username, self.settings.password)
            smtp.send_message(message)

    def mark_processed(self, incoming: IncomingMessage) -> None:
        self.connection.uid("store", incoming.uid, "+FLAGS", "(\\Seen)")

    def close(self) -> None:
        try:
            self.connection.close()
        finally:
            self.connection.logout()

    @staticmethod
    def _parse_message(uid: str, raw: bytes) -> IncomingMessage:
        message = BytesParser(policy=default).parsebytes(raw)
        sender = parseaddr(message.get("From", ""))[1]
        return IncomingMessage(
            uid=uid,
            sender=sender,
            subject=message.get("Subject", ""),
            body=_text_body(message),
            message_id=message.get("Message-ID", ""),
        )


def _text_body(message: EmailMessage) -> str:
    if not message.is_multipart():
        return message.get_content() if message.get_content_type() == "text/plain" else ""

    for part in message.walk():
        if (
            part.get_content_type() == "text/plain"
            and part.get_content_disposition() != "attachment"
        ):
            return part.get_content()
    return ""
