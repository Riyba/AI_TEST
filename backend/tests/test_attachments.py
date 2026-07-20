"""Attachment classification and content-block conversion (app/attachments.py)."""

from __future__ import annotations

import pytest

from app.attachments import (
    MAX_TEXT_CHARS,
    AttachmentContent,
    classify,
    to_content_blocks,
)

# A 1x1 PNG's leading bytes are enough; content isn't inspected, only mime.
PNG = b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------- #
# classify                                                                    #
# --------------------------------------------------------------------------- #


def test_classify_png_by_content_type() -> None:
    assert classify("logo.png", "image/png", PNG) == ("image", "image/png")


def test_classify_pdf() -> None:
    assert classify("doc.pdf", "application/pdf", b"%PDF-1.4") == ("pdf", "application/pdf")


def test_classify_text() -> None:
    kind, mime = classify("notes.txt", "text/plain", b"hello")
    assert kind == "text"


def test_classify_falls_back_to_extension() -> None:
    """octet-stream content type => guess from the filename."""
    kind, mime = classify("logo.png", "application/octet-stream", PNG)
    assert kind == "image" and mime == "image/png"


def test_classify_rejects_binary_non_media() -> None:
    with pytest.raises(ValueError, match="unsupported file type"):
        classify("blob.bin", "application/octet-stream", b"\xff\xfe\x00\x01")


# --------------------------------------------------------------------------- #
# to_content_blocks                                                          #
# --------------------------------------------------------------------------- #


def test_media_blocks_come_before_text_blocks() -> None:
    atts = [
        AttachmentContent("notes.txt", "text/plain", "text", b"read me"),
        AttachmentContent("logo.png", "image/png", "image", PNG),
    ]
    blocks = to_content_blocks(atts)
    # Image (media) first, text second, regardless of input order.
    assert blocks[0]["type"] == "image"
    assert blocks[1]["type"] == "text"


def test_image_block_is_base64() -> None:
    blocks = to_content_blocks([AttachmentContent("l.png", "image/png", "image", PNG)])
    src = blocks[0]["source"]
    assert src["type"] == "base64"
    assert src["media_type"] == "image/png"
    assert isinstance(src["data"], str) and src["data"]


def test_pdf_block_is_document() -> None:
    blocks = to_content_blocks([AttachmentContent("d.pdf", "application/pdf", "pdf", b"%PDF")])
    assert blocks[0]["type"] == "document"


def test_text_block_includes_filename() -> None:
    blocks = to_content_blocks([AttachmentContent("a.txt", "text/plain", "text", b"body")])
    assert "Attached file: a.txt" in blocks[0]["text"]
    assert "body" in blocks[0]["text"]


def test_long_text_is_truncated() -> None:
    big = b"x" * (MAX_TEXT_CHARS + 500)
    blocks = to_content_blocks([AttachmentContent("big.txt", "text/plain", "text", big)])
    assert "(file truncated)" in blocks[0]["text"]
