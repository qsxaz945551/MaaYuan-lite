"""Request-body parsing: the WPF client's POSTs arrive chunked.

``JsonContent`` cannot report its length, so ``HttpClient`` frames the body with
``Transfer-Encoding: chunked``. Reading only ``Content-Length`` silently turned
every save into an empty payload -- the option switch flipped back, the
dropdowns did nothing, and no error pointed at the cause.
"""

from __future__ import annotations

import unittest
from io import BytesIO

from lite.http_body import read_body


class Headers:
    def __init__(self, **values: str) -> None:
        self._values = {key.lower(): value for key, value in values.items()}

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._values.get(name.lower(), default)


class ReadBodyTest(unittest.TestCase):
    def test_content_length(self) -> None:
        stream = BytesIO(b'{"task":"a"}')
        self.assertEqual(read_body(stream, Headers(**{"Content-Length": "12"})), b'{"task":"a"}')

    def test_content_length_larger_than_body_reads_what_exists(self) -> None:
        stream = BytesIO(b"{}")
        self.assertEqual(read_body(stream, Headers(**{"Content-Length": "9"})), b"{}")

    def test_missing_headers_means_no_body(self) -> None:
        self.assertEqual(read_body(BytesIO(b"leftover"), Headers()), b"")

    def test_zero_length(self) -> None:
        self.assertEqual(read_body(BytesIO(b""), Headers(**{"Content-Length": "0"})), b"")

    def test_chunked_single_chunk(self) -> None:
        stream = BytesIO(b'c\r\n{"task":"a"}\r\n0\r\n\r\n')
        self.assertEqual(read_body(stream, Headers(**{"Transfer-Encoding": "chunked"})), b'{"task":"a"}')

    def test_chunked_multiple_chunks(self) -> None:
        stream = BytesIO(b'7\r\n{"task"\r\n6\r\n:"ok"}\r\n0\r\n\r\n')
        headers = Headers(**{"Transfer-Encoding": "chunked"})
        self.assertEqual(read_body(stream, headers), b'{"task":"ok"}')

    def test_chunked_ignores_chunk_extension(self) -> None:
        stream = BytesIO(b'7;foo=bar\r\n{"task"\r\n0\r\n\r\n')
        headers = Headers(**{"Transfer-Encoding": "chunked"})
        self.assertEqual(read_body(stream, headers), b'{"task"')

    def test_chunked_skips_trailer(self) -> None:
        stream = BytesIO(b'2\r\n{}\r\n0\r\nX-Checksum: 1\r\n\r\n')
        headers = Headers(**{"Transfer-Encoding": "chunked"})
        self.assertEqual(read_body(stream, headers), b"{}")

    def test_chunked_wins_over_content_length(self) -> None:
        stream = BytesIO(b'2\r\n{}\r\n0\r\n\r\n')
        headers = Headers(**{"Transfer-Encoding": "chunked", "Content-Length": "2"})
        self.assertEqual(read_body(stream, headers), b"{}")


if __name__ == "__main__":
    unittest.main()
