"""Safe upload storage (spec section 23).

Rules enforced here:
  * only PDF and DOCX, validated by magic bytes as well as extension;
  * a hard size cap;
  * randomized storage names, so a hostile filename cannot influence the path;
  * every resolved path re-checked to be inside the upload directory.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
}

# Magic bytes. DOCX is a zip container, hence the PK signature.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRejected(ValueError):
    """Raised when an upload fails validation."""

    def __init__(self, message: str, *, code: str = "invalid_upload"):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class StoredFile:
    storage_path: str
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    extension: str


def safe_display_name(filename: str | None) -> str:
    """Sanitize a filename for display. Never used to build a path."""
    base = os.path.basename(filename or "resume")
    base = _SAFE_NAME_RE.sub("_", base).strip("._-")
    return (base or "resume")[:200]


def detect_kind(content: bytes) -> str | None:
    """Return 'pdf' or 'docx' from the file's leading bytes, else None."""
    if content.startswith(_PDF_MAGIC):
        return "pdf"
    if any(content.startswith(sig) for sig in _ZIP_MAGIC):
        return "docx"
    return None


def upload_root() -> Path:
    root = settings.upload_dir
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def validate_and_store(
    content: bytes, filename: str | None, content_type: str | None
) -> StoredFile:
    """Validate an uploaded resume and write it under a random name."""
    if not content:
        raise UploadRejected("The uploaded file is empty.", code="empty_file")

    limit = settings.max_upload_bytes
    if len(content) > limit:
        raise UploadRejected(
            f"The file is {len(content) // 1024} KB, above the "
            f"{limit // 1024} KB limit.",
            code="file_too_large",
        )

    display_name = safe_display_name(filename)
    extension = Path(display_name).suffix.lower()

    kind = detect_kind(content)
    if kind is None:
        raise UploadRejected(
            "Only PDF and DOCX resumes are accepted. The file's contents did not "
            "match either format.",
            code="unsupported_type",
        )

    expected_ext = ".pdf" if kind == "pdf" else ".docx"
    # Extension and contents must agree: a .pdf that is really a zip is rejected.
    if extension and extension != expected_ext:
        raise UploadRejected(
            f"The file extension {extension} does not match its actual content "
            f"({expected_ext}).",
            code="extension_mismatch",
        )

    resolved_type = (
        "application/pdf"
        if kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    if content_type and content_type.lower() not in ALLOWED_TYPES and content_type != "application/octet-stream":
        # A wrong declared type is not fatal because browsers are unreliable
        # here, but it must not override what the bytes say.
        resolved_type = resolved_type

    root = upload_root()
    stored_name = f"{secrets.token_urlsafe(24)}{expected_ext}"
    target = (root / stored_name).resolve()

    # Defence in depth: the resolved path must stay inside the upload root.
    if not str(target).startswith(str(root) + os.sep):
        raise UploadRejected("Refusing to write outside the upload directory.", code="path_error")

    target.write_bytes(content)

    return StoredFile(
        storage_path=str(target),
        original_filename=display_name if extension else f"{display_name}{expected_ext}",
        content_type=resolved_type,
        size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        extension=expected_ext,
    )


def resolve_stored_path(storage_path: str) -> Path:
    """Resolve a stored path for reading, refusing anything outside the root."""
    root = upload_root()
    target = Path(storage_path).resolve()
    if not str(target).startswith(str(root) + os.sep):
        raise UploadRejected("That file is outside the upload directory.", code="path_error")
    if not target.is_file():
        raise UploadRejected("The stored file is missing.", code="file_missing")
    return target


def delete_stored(storage_path: str) -> bool:
    try:
        resolve_stored_path(storage_path).unlink()
        return True
    except (UploadRejected, OSError):
        return False
