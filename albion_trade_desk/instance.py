"""A process-lifetime lock; stale files are harmless after OS releases the lock."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, directory):
        self.path = Path(directory) / 'application.lock'
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            if self.path.stat().st_size == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise ValueError('Trade Desk уже запущен с этой базой. Откройте его вкладку или закройте предыдущую программу.') from exc
        self.stream = stream

    def close(self):
        if self.stream:
            self.stream.close()  # OS releases the lock, including on crash.
            self.stream = None
