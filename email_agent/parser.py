"""Parse the small request format understood by the email agent."""

import re
from dataclasses import dataclass

from regulatory_ingest.portal import DOCUMENT_TYPES


class RequestParseError(ValueError):
    """The email did not contain a supported request."""


@dataclass(frozen=True)
class AgentRequest:
    matter_number: str
    document_type: str


def parse_request(subject: str, body: str) -> AgentRequest:
    text = f"{subject}\n{body}"
    matter_match = re.search(r"\bM\d{5}\b", text, flags=re.IGNORECASE)
    if not matter_match:
        raise RequestParseError("I could not find a matter number such as M12205.")

    document_type = next(
        (
            supported_type
            for supported_type in DOCUMENT_TYPES
            if re.search(re.escape(supported_type), text, flags=re.IGNORECASE)
        ),
        None,
    )
    if document_type is None:
        choices = ", ".join(DOCUMENT_TYPES)
        raise RequestParseError(f"I could not find a document type. Choose: {choices}.")

    return AgentRequest(matter_match.group(0).upper(), document_type)
