from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(base_dir: str | None = None) -> None:
    """
    Minimal .env loader (no external dependency).
    Loads KEY=VALUE lines into os.environ if not already set.
    """
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

