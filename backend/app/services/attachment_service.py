"""Attachments: allowlisted types checked by extension and magic bytes, images re-encoded,
Office/ODF archives inspected, files stored under random names outside the web root."""

import hashlib
import io
import logging
import os
import re
import secrets
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Attachment, Page

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression bombs raise instead of exhausting memory

ZIP_MAX_ENTRIES = 2_000
ZIP_MAX_TOTAL = 100 * 1024 * 1024
ZIP_MAX_RATIO = 100
ORPHAN_GRACE = timedelta(hours=1)


@dataclass(frozen=True)
class FileKind:
    content_type: str
    family: str  # "image" | "pdf" | "ooxml" | "odf" | "text"
    image_format: str | None = None


KINDS: dict[str, FileKind] = {
    "png": FileKind("image/png", "image", "PNG"),
    "jpg": FileKind("image/jpeg", "image", "JPEG"),
    "jpeg": FileKind("image/jpeg", "image", "JPEG"),
    "gif": FileKind("image/png", "image", "PNG"),  # first frame, re-encoded as PNG
    "webp": FileKind("image/webp", "image", "WEBP"),
    "pdf": FileKind("application/pdf", "pdf"),
    "docx": FileKind(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "ooxml"
    ),
    "xlsx": FileKind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "ooxml"),
    "pptx": FileKind(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", "ooxml"
    ),
    "odt": FileKind("application/vnd.oasis.opendocument.text", "odf"),
    "ods": FileKind("application/vnd.oasis.opendocument.spreadsheet", "odf"),
    "odp": FileKind("application/vnd.oasis.opendocument.presentation", "odf"),
    "txt": FileKind("text/plain; charset=utf-8", "text"),
    "md": FileKind("text/plain; charset=utf-8", "text"),
    "csv": FileKind("text/plain; charset=utf-8", "text"),
    "log": FileKind("text/plain; charset=utf-8", "text"),
}
REFUSED_ACTIVE = {"svg", "svgz", "html", "htm", "xhtml", "xml", "js", "mjs"}
_UNSAFE_NAME = re.compile(r"[^\w .()\-]+")


def _rejected(reason: str) -> AppError:
    return AppError(422, "ATTACHMENT_REJECTED", f"File refused: {reason}", {"reason": reason})


def sanitize_filename(raw: str) -> str:
    """Last path component only, no control or special characters, at most 200 characters."""
    name = unicodedata.normalize("NFC", raw.replace("\\", "/").rsplit("/", 1)[-1])
    name = _UNSAFE_NAME.sub("_", name).strip(" .")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem[: 200 - len(ext) - 1] or "file"
    return f"{stem}.{ext}" if ext else stem


def _magic_matches(family: str, extension: str, data: bytes) -> bool:
    if family == "image":
        return {
            "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpg": data.startswith(b"\xff\xd8\xff"),
            "jpeg": data.startswith(b"\xff\xd8\xff"),
            "gif": data[:6] in (b"GIF87a", b"GIF89a"),
            "webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        }[extension]
    if family == "pdf":
        return data.startswith(b"%PDF-")
    if family in ("ooxml", "odf"):
        return data.startswith(b"PK\x03\x04")
    return True


def _reencode(data: bytes, image_format: str) -> bytes:
    """Decode and re-encode: drops EXIF/GPS metadata and any trailing polyglot payload."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            source.load()
            frame = source.convert("RGBA" if image_format in ("PNG", "WEBP") else "RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise _rejected("the image cannot be decoded") from exc
    output = io.BytesIO()
    options = {"quality": 90} if image_format in ("JPEG", "WEBP") else {}
    frame.save(output, format=image_format, **options)
    return output.getvalue()


def _check_archive(data: bytes, family: str) -> None:
    """Office/ODF documents are ZIP archives: refuse bombs, traversal names and macros."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _rejected("the document is not a valid archive") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > ZIP_MAX_ENTRIES or sum(e.file_size for e in entries) > ZIP_MAX_TOTAL:
            raise _rejected("the document expands to too much data")
        names = {e.filename for e in entries}
        for entry in entries:
            if entry.compress_size and entry.file_size / entry.compress_size > ZIP_MAX_RATIO:
                raise _rejected("the document is compressed suspiciously well")
            if entry.filename.startswith(("/", "\\")) or ".." in entry.filename.replace(
                "\\", "/"
            ).split("/"):
                raise _rejected("the document contains unsafe paths")
            if entry.filename.lower().endswith("vbaproject.bin"):
                raise _rejected("documents with macros are not accepted")
        if family == "ooxml":
            if "[Content_Types].xml" not in names:
                raise _rejected("the document is not an Office file")
            if b"macroenabled" in archive.read("[Content_Types].xml")[:1_000_000].lower():
                raise _rejected("documents with macros are not accepted")
        if family == "odf" and (
            "mimetype" not in names or any(n.startswith("Basic/") for n in names)
        ):
            raise _rejected("the document is not an OpenDocument file or contains macros")


def validate(filename: str, data: bytes) -> tuple[str, FileKind, bytes]:
    """Return ``(safe_name, kind, stored_bytes)`` or raise 422."""
    name = sanitize_filename(filename)
    extension = name.rpartition(".")[2].lower() if "." in name else ""
    if extension in REFUSED_ACTIVE:
        raise _rejected("SVG, HTML and script files are not accepted")
    kind = KINDS.get(extension)
    if kind is None:
        raise _rejected("this file type is not accepted")
    if not data:
        raise _rejected("the file is empty")
    if not _magic_matches(kind.family, extension, data):
        raise _rejected("the content does not match the file extension")
    if kind.family == "image":
        data = _reencode(data, kind.image_format or "PNG")
        if extension == "gif":
            name = f"{name.rpartition('.')[0]}.png"
    elif kind.family in ("ooxml", "odf"):
        _check_archive(data, kind.family)
    elif kind.family == "text":
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _rejected("text files must be UTF-8") from exc
        if "\x00" in decoded:
            raise _rejected("the content does not match the file extension")
    return name, kind, data


def store(
    db: Session, storage_dir: Path, page: Page, uploader_id: uuid.UUID, filename: str, data: bytes
) -> Attachment:
    name, kind, stored = validate(filename, data)
    key = secrets.token_hex(16)
    path = storage_dir / key
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, stored)
    finally:
        os.close(fd)
    attachment = Attachment(
        id=uuid.uuid4(),
        page_id=page.id,
        uploaded_by=uploader_id,
        filename=name,
        storage_key=key,
        content_type=kind.content_type,
        size_bytes=len(stored),
        sha256=hashlib.sha256(stored).hexdigest(),
        inline_allowed=kind.family == "image",
    )
    db.add(attachment)
    return attachment


def path_of(storage_dir: Path, attachment: Attachment) -> Path:
    path = (storage_dir / attachment.storage_key).resolve()
    if not path.is_relative_to(storage_dir.resolve()):
        raise AppError(404, "NOT_FOUND", "Not found")
    return path


def remove_file(storage_dir: Path, attachment: Attachment) -> None:
    path_of(storage_dir, attachment).unlink(missing_ok=True)


def purge_orphans(db: Session, storage_dir: Path) -> int:
    """Delete stored files with no database row (pages purged with their attachments)."""
    if not storage_dir.is_dir():
        return 0
    known = set(db.scalars(select(Attachment.storage_key)).all())
    cutoff = (datetime.now(UTC) - ORPHAN_GRACE).timestamp()
    removed = 0
    for entry in storage_dir.iterdir():
        if entry.is_file() and entry.name not in known and entry.stat().st_mtime < cutoff:
            entry.unlink(missing_ok=True)
            removed += 1
    if removed:
        logger.info("Orphaned attachment files removed", extra={"count": removed})
    return removed
