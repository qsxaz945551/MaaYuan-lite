"""Read an HTTP request body regardless of how the client framed it.

``Content-Length`` is the common case, but HTTP/1.1 also allows chunked
transfer. ``System.Net.Http.Json.JsonContent`` cannot report a length, so
``HttpClient`` sends chunked -- and an earlier version of this server read only
``Content-Length``, which turned every WPF POST into an empty dict. The failure
was silent: task options simply refused to save, with no error anywhere near
the actual cause.
"""

from __future__ import annotations

from typing import BinaryIO, Protocol


class _HeadersLike(Protocol):
    def get(self, name: str, default: str = ...) -> str | None: ...


def read_body(stream: BinaryIO, headers: _HeadersLike) -> bytes:
    """Return the raw request body."""
    if "chunked" in (headers.get("Transfer-Encoding") or "").lower():
        return _read_chunked(stream)
    length = int(headers.get("Content-Length") or 0)
    return stream.read(length) if length > 0 else b""


def _read_chunked(stream: BinaryIO) -> bytes:
    chunks: list[bytes] = []
    while True:
        line = stream.readline(65536)
        if not line:
            break
        size_field = line.split(b";", 1)[0].strip()
        if not size_field:
            break
        try:
            size = int(size_field, 16)
        except ValueError:
            break
        if size == 0:
            # Trailer section: either CRLF alone, or header lines then CRLF.
            while True:
                trailer = stream.readline(65536)
                if not trailer or trailer in (b"\r\n", b"\n"):
                    break
            break
        chunks.append(stream.read(size))
        stream.read(2)  # trailing CRLF of the chunk
    return b"".join(chunks)
