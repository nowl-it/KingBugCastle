"""Body caps must also apply to chunked/direct-route request readers."""
import asyncio
from pathlib import Path
import sys


_SERVER = Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from security import read_capped_body


class _ChunkedRequest:
    def __init__(self, *chunks):
        self._chunks = chunks

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


def test_chunked_body_is_capped_while_streaming():
    request = _ChunkedRequest(b"abc", b"def")
    assert asyncio.run(read_capped_body(request, 6)) == b"abcdef"

    oversized = _ChunkedRequest(b"abc", b"def", b"g")
    try:
        asyncio.run(read_capped_body(oversized, 6))
    except ValueError as exc:
        assert "body exceeded 6 bytes" in str(exc)
    else:
        raise AssertionError("chunked body was not capped")
