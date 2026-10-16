"""Encrypted, streamed backup archive format.

Layers, outermost first:

1. Encryption: ``MAGIC | salt | key id`` header, then frames ``flag | length | ciphertext``. Each
   frame is AES-256-GCM under a per-file key (HKDF of the backup key and the salt), with the frame
   counter as nonce and ``header | counter | flag`` as associated data. Reordering, truncation (the
   last frame carries the final flag) and tampering are detected.
2. zlib compression of the plaintext stream.
3. Entries: ``"E" | name length | name``, then data chunks ``length | bytes`` ended by a zero
   length; ``"Z"`` closes the archive.

The backup key is never stored with the backups. Nothing here needs a subprocess.
"""

import hashlib
import json
import secrets
import struct
import zlib
from collections.abc import Iterable, Iterator
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"WIKIBKP1"
SALT_BYTES = 16
KEY_ID_BYTES = 8
FRAME_BYTES = 1024 * 1024
MAX_FRAME_BYTES = FRAME_BYTES + 16
_FINAL = b"\x01"
_MORE = b"\x00"


class BackupFormatError(ValueError):
    """Unreadable backup: wrong key, damaged, truncated or tampered with."""


def key_id(key: bytes) -> bytes:
    """Short fingerprint of the backup key, so a wrong key is reported as such."""
    return hashlib.sha256(b"wiki-backup-key-id\x00" + key).digest()[:KEY_ID_BYTES]


def _file_key(key: bytes, salt: bytes) -> AESGCM:
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"wiki-backup-v1")
    return AESGCM(derived.derive(key))


def _nonce(counter: int) -> bytes:
    return b"\x00" * 4 + counter.to_bytes(8, "big")


def _aad(header: bytes, counter: int, flag: bytes) -> bytes:
    return header + counter.to_bytes(8, "big") + flag


class _EncryptedWriter:
    def __init__(self, out: BinaryIO, key: bytes) -> None:
        salt = secrets.token_bytes(SALT_BYTES)
        self._out = out
        self._header = MAGIC + salt + key_id(key)
        self._aead = _file_key(key, salt)
        self._counter = 0
        self._buffer = bytearray()
        out.write(self._header)

    def write(self, data: bytes) -> None:
        self._buffer += data
        while len(self._buffer) > FRAME_BYTES:
            self._emit(bytes(self._buffer[:FRAME_BYTES]), _MORE)
            del self._buffer[:FRAME_BYTES]

    def close(self) -> None:
        self._emit(bytes(self._buffer), _FINAL)
        self._buffer.clear()

    def _emit(self, plaintext: bytes, flag: bytes) -> None:
        aad = _aad(self._header, self._counter, flag)
        ciphertext = self._aead.encrypt(_nonce(self._counter), plaintext, aad)
        self._out.write(flag + struct.pack(">I", len(ciphertext)) + ciphertext)
        self._counter += 1


def _decrypted_frames(stream: BinaryIO, key: bytes) -> Iterator[bytes]:
    header = stream.read(len(MAGIC) + SALT_BYTES + KEY_ID_BYTES)
    if len(header) != len(MAGIC) + SALT_BYTES + KEY_ID_BYTES or not header.startswith(MAGIC):
        raise BackupFormatError("Not a wiki backup")
    if header[-KEY_ID_BYTES:] != key_id(key):
        raise BackupFormatError("This backup was encrypted with another backup key")
    aead = _file_key(key, header[len(MAGIC) : len(MAGIC) + SALT_BYTES])
    counter = 0
    while True:
        prefix = stream.read(5)
        if len(prefix) != 5:  # noqa: PLR2004
            raise BackupFormatError("The backup is truncated")
        flag, length = prefix[:1], struct.unpack(">I", prefix[1:])[0]
        if flag not in (_FINAL, _MORE) or length > MAX_FRAME_BYTES:
            raise BackupFormatError("The backup is damaged")
        ciphertext = stream.read(length)
        if len(ciphertext) != length:
            raise BackupFormatError("The backup is truncated")
        try:
            yield aead.decrypt(_nonce(counter), ciphertext, _aad(header, counter, flag))
        except InvalidTag as exc:
            raise BackupFormatError("The backup has been modified or is damaged") from exc
        counter += 1
        if flag == _FINAL:
            if stream.read(1):
                raise BackupFormatError("Unexpected data after the end of the backup")
            return


def _plaintext(stream: BinaryIO, key: bytes) -> Iterator[bytes]:
    decompressor = zlib.decompressobj()
    for frame in _decrypted_frames(stream, key):
        data = decompressor.decompress(frame)
        if data:
            yield data
    tail = decompressor.flush()
    if tail:
        yield tail
    if not decompressor.eof:
        raise BackupFormatError("The backup is truncated")


class ArchiveWriter:
    """Writes entries in order; ``close()`` must be called to make the archive valid."""

    def __init__(self, out: BinaryIO, key: bytes) -> None:
        self._encrypted = _EncryptedWriter(out, key)
        self._compressor = zlib.compressobj(6)

    def _put(self, data: bytes) -> None:
        compressed = self._compressor.compress(data)
        if compressed:
            self._encrypted.write(compressed)

    def add(self, name: str, chunks: Iterable[bytes]) -> int:
        """Add an entry from a stream of chunks; returns its size in bytes."""
        encoded = name.encode("utf-8")
        self._put(b"E" + struct.pack(">H", len(encoded)) + encoded)
        size = 0
        for chunk in chunks:
            for start in range(0, len(chunk), FRAME_BYTES):
                part = chunk[start : start + FRAME_BYTES]
                self._put(struct.pack(">I", len(part)) + part)
                size += len(part)
        self._put(struct.pack(">I", 0))
        return size

    def add_json(self, name: str, value: Any) -> None:
        self.add(name, [json.dumps(value, sort_keys=True).encode()])

    def close(self) -> None:
        self._put(b"Z")
        self._encrypted.write(self._compressor.flush())
        self._encrypted.close()


class _Source:
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buffer = bytearray()

    def read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = next(self._chunks, None)
            if chunk is None:
                raise BackupFormatError("The backup is truncated")
            self._buffer += chunk
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def ensure_end(self) -> None:
        if self._buffer or any(self._chunks):
            raise BackupFormatError("Unexpected data after the end of the backup")


class ArchiveReader:
    """Reads entries in order. Each entry's data must be consumed before the next one."""

    def __init__(self, stream: BinaryIO, key: bytes) -> None:
        self._source = _Source(_plaintext(stream, key))

    def _data(self) -> Iterator[bytes]:
        while True:
            length = struct.unpack(">I", self._source.read(4))[0]
            if length == 0:
                return
            if length > FRAME_BYTES:
                raise BackupFormatError("The backup is damaged")
            yield self._source.read(length)

    def entries(self) -> Iterator[tuple[str, Iterator[bytes]]]:
        while True:
            kind = self._source.read(1)
            if kind == b"Z":
                self._source.ensure_end()
                return
            if kind != b"E":
                raise BackupFormatError("The backup is damaged")
            length = struct.unpack(">H", self._source.read(2))[0]
            name = self._source.read(length).decode("utf-8")
            data = self._data()
            yield name, data
            for _ in data:
                pass

    @staticmethod
    def read_json(data: Iterator[bytes]) -> Any:
        return json.loads(b"".join(data))
