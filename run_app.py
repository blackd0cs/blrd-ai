"""Локальный запуск API: Run ▶ в PyCharm или `python run_app.py`."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def preflight() -> None:
    """Проверяет, что app.main существует и отдаёт FastAPI, иначе объясняет что не так."""
    main_py = ROOT / "app" / "main.py"
    if (ROOT / "app" / "main").is_dir():
        raise SystemExit(f"{ROOT / 'app' / 'main'} — это папка, а должен быть файл main.py")
    if not main_py.exists():
        raise SystemExit(f"нет файла {main_py}")
    if main_py.stat().st_size < 200:
        raise SystemExit(f"{main_py} почти пустой ({main_py.stat().st_size} байт) — файл не сохранён")

    import app.main as module

    target = getattr(module, "app", None)
    if target is None:
        raise SystemExit(
            f"в {module.__file__} нет объекта app. "
            "Должна быть строка: app = FastAPI(..., lifespan=lifespan)"
        )
    print(f"ok: {module.__file__} → {type(target).__name__}")


if __name__ == "__main__":
    preflight()

    import uvicorn

    from app.core.config import settings

    print(f"API: http://127.0.0.1:{settings.port}  ·  health: /health")
    uvicorn.run(
        "app.main:app",
        host=settings.public_host,
        port=settings.port,
        reload=True,
        reload_dirs=[str(ROOT / "app"), str(ROOT / "web"), str(ROOT / "config")],
        log_level=settings.log_level.lower(),
    )
