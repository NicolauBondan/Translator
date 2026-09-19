# -*- coding: utf-8 -*-
"""Ponto de entrada do aplicativo instalado (ManhuaTranslator.exe).

Faz o que o app precisa antes de abrir a janela:
  • redireciona stdout/stderr (o .exe não tem console) para o arquivo de log;
  • liga o modo "DPI aware" no Windows (evita janela borrada em telas 125%/150%);
  • captura qualquer erro fatal, grava no log e mostra uma mensagem em vez de
    o programa simplesmente sumir.

Em desenvolvimento:  python launcher.py
"""
from __future__ import annotations

import logging
import multiprocessing
import sys
import traceback

import app_paths as ap


def _setup_logging() -> None:
    log_file = ap.log_path()
    try:
        if log_file.exists() and log_file.stat().st_size > 1_000_000:   # não deixa crescer sem limite
            log_file.write_text("", encoding="utf-8")
    except OSError:
        pass
    logging.basicConfig(filename=str(log_file), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    if ap.is_frozen():   # sem console: bibliotecas que escrevem em stderr não podem falhar
        stream = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream


def _dpi_aware() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def _fatal(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(ap.APP_TITLE, message)
        root.destroy()
    except Exception:
        print(message, file=sys.__stderr__ or sys.stderr)


def main() -> int:
    multiprocessing.freeze_support()
    _setup_logging()
    _dpi_aware()
    logging.info("Iniciando %s %s", ap.APP_TITLE, ap.APP_VERSION)
    try:
        import gui
        gui.main()
    except Exception:
        details = traceback.format_exc()
        logging.error("Erro fatal:\n%s", details)
        _fatal(f"O programa encontrou um erro e precisa fechar.\n\n"
               f"{details.strip().splitlines()[-1]}\n\n"
               f"Os detalhes foram salvos em:\n{ap.log_path()}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
