"""Small data objects shared by the pipeline modules."""

from dataclasses import dataclass


class PipelineError(RuntimeError):
    """A user-facing pipeline error."""


class MatterNotFound(PipelineError):
    """The portal did not find the requested matter."""


@dataclass(frozen=True)
class DocumentCandidate:
    document_type: str
    display_order: int
    document_number: str
    title: str
    security: str
    extension: str
    date_filed: str
    row_key: str


@dataclass
class DocumentRecord:
    document_type: str
    display_order: int
    document_number: str
    title: str
    security: str
    extension: str
    date_filed: str
    status: str = "pending"
    filename: str | None = None
    local_path: str | None = None
    error: str | None = None
