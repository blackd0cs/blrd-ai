from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings


class AlreadyRunning(RuntimeError):
    pass


def acquire(name: str = "bot") -> Path:
    """
    Один процесс на имя. Если PID из лока ещё жив — отказ;
    если умер (упал, убит), лок переписывается.
    """
    path = settings.data_dir / f"{name}.pid"
    if path.exists():
        try:
            old = int(path.read_text().strip() or 0)
        except ValueError:
            old = 0
        if old and old != os.getpid() and _alive(old):
            raise AlreadyRunning(
                f"процесс {name} уже запущен (PID {old}). "
                f"Остановите его или удалите {path}"
            )
    path.write_text(str(os.getpid()))
    return path


def release(path: Path) -> None:
    try:
        if path.exists() and path.read_text().strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
