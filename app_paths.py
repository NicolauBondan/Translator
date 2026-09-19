# -*- coding: utf-8 -*-
"""Caminhos, versão e configurações do usuário.

Funciona igual no Python normal e no aplicativo empacotado com PyInstaller.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "ManhuaTranslator"     # nome de pasta / executável
APP_TITLE = "Manhua Translator"   # nome exibido
APP_VERSION = "1.0.0"             # única fonte da versão (o instalador lê daqui)


def is_frozen() -> bool:
    """True quando rodando como aplicativo empacotado (.exe)."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Pasta com os arquivos empacotados junto do app (fonts/, assets/)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    """Pasta gravável do usuário (configurações, log, fontes extras)."""
    override = os.environ.get("MANHUA_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(root) / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def log_path() -> Path:
    return user_dir() / "log.txt"


def load_settings() -> dict:
    try:
        return json.loads((user_dir() / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        (user_dir() / "settings.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
