"""Attachment handling: validation/classification at upload time, and
conversion into Anthropic message content blocks at run time.

Attachments come in three kinds:
- image (png/jpeg/gif/webp)  -> base64 image content block
- pdf                        -> base64 document content block
- text (anything utf-8)      -> inline text block, truncated if huge

Anything else is rejected at upload.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from typing import Any

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # per file; also the Anthropic image limit
MAX_TEXT_CHARS = 100_000  # inlined text is truncated beyond this

IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
PDF_MIME = "application/pdf"


@dataclass
class AttachmentContent:
    """In-memory attachment passed from the runner into agent nodes."""

    filename: str
    mime_type: str
    kind: str  # image | pdf | text
    data: bytes


def classify(filename: str, content_type: str | None, data: bytes) -> tuple[str, str]:
    """Return (kind, mime_type) for an upload, or raise ValueError."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(filename)[0] or ""

    if mime in IMAGE_MIMES:
        return "image", mime
    if mime == PDF_MIME:
        return "pdf", mime
    # Everything else must be readable as text.
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(
            f"unsupported file type for '{filename}': only images "
            "(png/jpeg/gif/webp), PDFs, and UTF-8 text files are accepted"
        ) from None
    return "text", mime or "text/plain"


def to_content_blocks(attachments: list[AttachmentContent]) -> list[dict[str, Any]]:
    """Build Anthropic content blocks. Media blocks come first, then text
    blocks, so callers can append the prompt text block last."""
    media: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    for att in attachments:
        if att.kind == "image":
            media.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att.mime_type,
                        "data": base64.standard_b64encode(att.data).decode("ascii"),
                    },
                }
            )
        elif att.kind == "pdf":
            media.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": PDF_MIME,
                        "data": base64.standard_b64encode(att.data).decode("ascii"),
                    },
                }
            )
        else:
            text = att.data.decode("utf-8", errors="replace")
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "\n… (file truncated)"
            texts.append(
                {
                    "type": "text",
                    "text": f"Attached file: {att.filename}\n\n{text}",
                }
            )
    return media + texts
