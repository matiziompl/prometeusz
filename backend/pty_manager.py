import asyncio
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
from typing import Callable, List, Optional


class PTYSession:
    """Manages an interactive process inside a Unix pseudo-terminal (PTY)."""

    def __init__(
        self,
        command: Optional[List[str]] = None,
        cwd: str = "/workspace",
        env: Optional[dict] = None,
        on_output: Optional[Callable[[bytes], None]] = None,
    ):
        self.command = command or ["/bin/bash"]
        self.cwd = cwd
        self.env = env or os.environ.copy()
        self.on_output = on_output
        self.master_fd: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None
        self.buffer = bytearray()
        self._read_task: Optional[asyncio.Task] = None
        self._is_running = False

    async def start(self):
        """Spawn the process attached to the slave PTY."""
        master_fd, slave_fd = pty.openpty()
        try:
            self.master_fd = master_fd

            # Set non-blocking on master_fd
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            self.proc = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.cwd,
                env=self.env,
                preexec_fn=os.setsid,
                close_fds=True,
            )
        except Exception:
            if self.master_fd is not None:
                os.close(self.master_fd)
                self.master_fd = None
            raise
        finally:
            os.close(slave_fd)

        self._is_running = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """Asynchronously read output from master_fd."""
        loop = asyncio.get_running_loop()
        while self._is_running and self.master_fd is not None:
            try:
                data = await loop.run_in_executor(None, self._nonblocking_read)
                if data:
                    self.buffer.extend(data)
                    if self.on_output:
                        try:
                            self.on_output(data)
                        except Exception:
                            pass
                else:
                    await asyncio.sleep(0.02)
            except (OSError, IOError):
                break
        self._is_running = False

    def _nonblocking_read(self) -> bytes:
        if self.master_fd is None:
            return b""
        try:
            return os.read(self.master_fd, 4096)
        except (BlockingIOError, InterruptedError):
            return b""
        except OSError:
            return b""

    def write(self, data: str | bytes):
        """Write input data to the PTY."""
        if self.master_fd is None or not self._is_running:
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int):
        """Resize the PTY terminal window with clamped dimensions."""
        if self.master_fd is not None:
            rows = max(1, min(int(rows), 1000))
            cols = max(1, min(int(cols), 1000))
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            try:
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass

    def is_alive(self) -> bool:
        """Check if child process is still running."""
        if self.proc is None:
            return False
        return self.proc.poll() is None

    async def read_until(self, target: str, timeout: float = 5.0) -> str:
        """Read until target string appears in output buffer or timeout is reached."""
        target_bytes = target.encode("utf-8")
        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout:
            if target_bytes in self.buffer:
                return self.buffer.decode("utf-8", errors="replace")
            await asyncio.sleep(0.05)
        return self.buffer.decode("utf-8", errors="replace")

    async def close(self):
        """Terminate the process group, prevent zombie processes, and close file descriptors."""
        self._is_running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        try:
            if self.proc and self.proc.poll() is None:
                pid = self.proc.pid
                loop = asyncio.get_running_loop()
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    try:
                        self.proc.terminate()
                    except OSError:
                        pass

                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, self.proc.wait),
                        timeout=1.0,
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    try:
                        pgid = os.getpgid(pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        try:
                            self.proc.kill()
                        except OSError:
                            pass
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, self.proc.wait),
                            timeout=1.0,
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
        finally:
            if self.master_fd is not None:
                try:
                    os.close(self.master_fd)
                except OSError:
                    pass
                self.master_fd = None
