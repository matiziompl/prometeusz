import asyncio
from typing import Optional, List


class MockPTYSession:
    """Mock PTY session that provides deterministic, instant I/O without spawning OS processes."""

    def __init__(self, command: Optional[List[str]] = None, cwd: str = "/workspace", **kwargs):
        self.command = command
        self.cwd = cwd
        self._is_alive = True
        self.buffer = bytearray()
        self._output_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self):
        self._is_alive = True

    def is_alive(self) -> bool:
        return self._is_alive

    def _nonblocking_read(self) -> bytes:
        try:
            return self._output_queue.get_nowait()
        except asyncio.QueueEmpty:
            return b""

    def write(self, data: str | bytes):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.buffer.extend(data)
        # Respond back immediately with simulated stdout
        self._output_queue.put_nowait(b"Echo: " + data)

    def resize(self, rows: int, cols: int):
        pass

    async def close(self):
        self._is_alive = False
