"""Read selected members of the exact public municipal migration ZIP using verified HTTP ranges."""

from __future__ import annotations

from io import RawIOBase
import re
import subprocess
import time
from urllib.request import Request, urlopen


class HTTPRangeReader(RawIOBase):
    def __init__(self, url: str, *, timeout: int = 60):
        if url != "https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20250918/indicators/section31/data_Y48112023_112_v20250918.zip":
            raise ValueError("unexpected municipal archive URL")
        self.url = url
        self.timeout = timeout
        with urlopen(Request(url, method="HEAD"), timeout=timeout) as response:
            if response.url != url:
                raise ValueError("unexpected archive redirect")
            self.size = int(response.headers["Content-Length"])
            self.etag = response.headers["ETag"]
        self.pos = 0
        self.downloaded_bytes = 0
        self.requests = 0
        self._cache_start = -1
        self._cache = b""

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            new = offset
        elif whence == 1:
            new = self.pos + offset
        elif whence == 2:
            new = self.size + offset
        else:
            raise ValueError("bad whence")
        if new < 0:
            raise ValueError("negative seek")
        self.pos = new
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        if n > 8_000_000:
            raise ValueError("single HTTP range too large")
        if self._cache_start <= self.pos and self.pos + n <= self._cache_start + len(self._cache):
            start = self.pos - self._cache_start
            out = self._cache[start:start + n]
            self.pos += n
            return out
        start = self.pos
        end = min(self.size - 1, start + max(n, 768_000) - 1)
        for attempt in range(4):
            try:
                result = subprocess.run(
                    ["curl", "--silent", "--show-error", "--max-time", str(min(self.timeout, 20)),
                     "--max-filesize", "8000000", "--header", f"Range: bytes={start}-{end}",
                     "--header", f"If-Match: {self.etag}", "--dump-header", "-", self.url],
                    capture_output=True, check=True, timeout=min(self.timeout, 20) + 5,
                )
                header, separator, raw = result.stdout.partition(b"\r\n\r\n")
                if not separator or not header.startswith((b"HTTP/2 206", b"HTTP/1.1 206")):
                    raise ValueError("server did not honor exact range")
                fields = dict(line.decode("latin1").split(": ", 1) for line in header.split(b"\r\n")[1:] if b": " in line)
                fields = {key.lower(): value for key, value in fields.items()}
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", fields.get("content-range", ""))
                if not match or tuple(map(int, match.groups())) != (start, end, self.size):
                    raise ValueError("unexpected Content-Range")
                if fields.get("etag") != self.etag:
                    raise ValueError("municipal archive changed during sampling")
                break
            except (OSError, subprocess.SubprocessError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        if len(raw) != end - start + 1:
            raise ValueError("truncated HTTP range")
        self._cache_start, self._cache = start, raw
        self.downloaded_bytes += len(raw)
        self.requests += 1
        self.pos += n
        return raw[:n]
