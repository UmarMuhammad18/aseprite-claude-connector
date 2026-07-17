"""Backend selection. One process = one backend, chosen by config."""

from __future__ import annotations

from ..config import load_config
from .base import Backend, ExecResult
from .headless import HeadlessBackend
from .live import LiveBackend

_backend: Backend | None = None


def get_backend() -> Backend:
    global _backend
    if _backend is None:
        cfg = load_config()
        if cfg.backend == "headless":
            _backend = HeadlessBackend(cfg.aseprite_path, cfg.exec_timeout)
        else:
            _backend = LiveBackend(cfg.relay_url, cfg.exec_timeout)
    return _backend


def set_backend(backend: Backend | None) -> None:
    """Override the backend (used by tests)."""
    global _backend
    _backend = backend


__all__ = ["Backend", "ExecResult", "get_backend", "set_backend", "LiveBackend", "HeadlessBackend"]
