# -*- coding: utf-8 -*-
"""Interface gráfica do Manhua Translator.

Abra pelo launcher (python launcher.py) ou direto:  python gui.py
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import app_paths as ap
import manhua_translator as mt

TARGET_LANGS = {"Português (BR)": "pt", "Inglês": "en", "Espanhol": "es", "Francês": "fr"}
ENGINES = {
    "Google Tradutor (grátis)": "google",
    "Claude (melhor qualidade — precisa de chave de API)": "claude",
}
PREVIEW_W, PREVIEW_H = 460, 620


def source_langs() -> dict:
    """Idiomas disponíveis conforme os motores de OCR instalados."""
    langs = {}
    if mt.rapidocr_available():
        langs["Chinês (manhua)"] = "ch_sim"
    if mt.easyocr_available():
        langs.setdefault("Chinês simplificado (manhua)", "ch_sim")
        langs.update({"Chinês tradicional": "ch_tra", "Japonês (mangá)": "ja",
                      "Coreano (manhwa)": "ko", "Inglês": "en"})
    return langs or {"Chinês (manhua)": "ch_sim"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = ap.load_settings()
        self.title(f"{ap.APP_TITLE} {ap.APP_VERSION}")
        self.geometry("1120x760")
        self.minsize(980, 660)
        self._set_icon()

        self.q: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.inputs: list = []
        self._photo = None
        self.src_langs = source_langs()

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

    def _set_icon(self):
        try:
            ico = ap.resource_dir() / "assets" / "icon.ico"
            png = ap.resource_dir() / "assets" / "icon.png"
            if sys.platform == "win32" and ico.exists():
                self.iconbitmap(str(ico))
            elif png.exists():
                self._icon_img = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    # ── layout ──────────────────────────────────────────────────────────────
    def _build(self):
        s = self.settings
        pick = lambda options, key: s.get(key) if s.get(key) in options else next(iter(options))
        pad = {"padx": 8, "pady": 4}

        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=10)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Entrada (pastas, imagens, .cbz/.zip)", font=("", 10, "bold")).pack(anchor="w")
        self.listbox = tk.Listbox(left, height=5, width=52)
        self.listbox.pack(fill="x", **pad)
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Button(row, text="+ Pasta", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(row, text="+ Arquivos", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(row, text="Limpar", command=self._clear).pack(side="left", padx=2)

        ttk.Label(left, text="Pasta de saída (opcional)", font=("", 10, "bold")).pack(anchor="w", pady=(12, 0))
        row = ttk.Frame(left)
        row.pack(fill="x", **pad)
        self.var_out = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_out).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="…", width=3, command=self._pick_out).pack(side="left", padx=(4, 0))

        grid = ttk.Frame(left)
        grid.pack(fill="x", pady=(12, 0))
        grid.columnconfigure(1, weight=1)
        self.var_src = tk.StringVar(value=pick(self.src_langs, "src"))
        self.var_dst = tk.StringVar(value=pick(TARGET_LANGS, "dst"))
        self.var_eng = tk.StringVar(value=pick(ENGINES, "engine"))
        for r, (label, var, values) in enumerate([
            ("Idioma original", self.var_src, list(self.src_langs)),
            ("Traduzir para", self.var_dst, list(TARGET_LANGS)),
            ("Motor", self.var_eng, list(ENGINES)),
        ]):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Combobox(grid, textvariable=var, values=values, state="readonly", width=34).grid(
                row=r, column=1, sticky="ew", **pad)

        ttk.Label(grid, text="Chave API Claude").grid(row=3, column=0, sticky="w", **pad)
        self.var_key = tk.StringVar(value=s.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", ""))
        ttk.Entry(grid, textvariable=self.var_key, show="•").grid(row=3, column=1, sticky="ew", **pad)
        self.var_remember = tk.BooleanVar(value=bool(s.get("api_key")))
        ttk.Checkbutton(grid, text="Lembrar a chave neste computador", variable=self.var_remember).grid(
            row=4, column=1, sticky="w", padx=8)

        ttk.Label(grid, text="Fonte (.ttf)").grid(row=5, column=0, sticky="w", **pad)
        frow = ttk.Frame(grid)
        frow.grid(row=5, column=1, sticky="ew", **pad)
        self.var_font = tk.StringVar(value=s.get("font", ""))
        ttk.Entry(frow, textvariable=self.var_font).pack(side="left", fill="x", expand=True)
        ttk.Button(frow, text="…", width=3, command=self._pick_font).pack(side="left", padx=(4, 0))

        self.var_upper = tk.BooleanVar(value=s.get("upper", True))
        self.var_cbz = tk.BooleanVar(value=s.get("cbz", False))
        self.var_gpu = tk.BooleanVar(value=s.get("gpu", True))
        self.var_dbg = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="Texto em MAIÚSCULAS (padrão de quadrinhos)", variable=self.var_upper).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(left, text="Gerar também um arquivo .cbz", variable=self.var_cbz).pack(anchor="w")
        if mt.easyocr_available():
            ttk.Checkbutton(left, text="Usar GPU se disponível", variable=self.var_gpu).pack(anchor="w")
        ttk.Checkbutton(left, text="Salvar imagens de depuração (caixas)", variable=self.var_dbg).pack(anchor="w")

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(16, 0))
        self.btn_go = ttk.Button(row, text="▶  Traduzir", command=self._start)
        self.btn_go.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_stop = ttk.Button(row, text="Cancelar", command=self.stop_flag.set, state="disabled")
        self.btn_stop.pack(side="left")
        self.btn_open = ttk.Button(left, text="Abrir pasta de saída", command=self._open_out, state="disabled")
        self.btn_open.pack(fill="x", pady=(6, 0))
        ttk.Label(left, text=f"Versão {ap.APP_VERSION}  •  log: {ap.log_path()}",
                  foreground="gray", wraplength=380).pack(anchor="w", pady=(14, 0))

        self.preview = ttk.Label(right, text="A prévia da última página traduzida aparece aqui",
                                 anchor="center", relief="groove")
        self.preview.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(right, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 4))
        self.log = tk.Text(right, height=9, state="disabled", wrap="word")
        self.log.pack(fill="x")

    # ── ações ───────────────────────────────────────────────────────────────
    def _add_folder(self):
        p = filedialog.askdirectory(title="Escolha a pasta com as páginas")
        if p:
            self._add([p])

    def _add_files(self):
        ps = filedialog.askopenfilenames(
            title="Escolha imagens ou .cbz/.zip",
            filetypes=[("Imagens e volumes", "*.jpg *.jpeg *.png *.webp *.bmp *.cbz *.zip"), ("Todos", "*.*")])
        if ps:
            self._add(list(ps))

    def _add(self, paths):
        for p in paths:
            if p not in self.inputs:
                self.inputs.append(p)
                self.listbox.insert("end", p)

    def _clear(self):
        self.inputs.clear()
        self.listbox.delete(0, "end")

    def _pick_out(self):
        p = filedialog.askdirectory(title="Pasta de saída")
        if p:
            self.var_out.set(p)

    def _pick_font(self):
        p = filedialog.askopenfilename(title="Fonte", filetypes=[("Fontes", "*.ttf *.otf")])
        if p:
            self.var_font.set(p)

    def _open_out(self):
        p = self.var_out.get().strip()
        if not p or not Path(p).exists():
            return
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])

    def _write_log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _save_settings(self):
        data = {"src": self.var_src.get(), "dst": self.var_dst.get(), "engine": self.var_eng.get(),
                "font": self.var_font.get().strip(), "upper": self.var_upper.get(),
                "cbz": self.var_cbz.get(), "gpu": self.var_gpu.get()}
        if self.var_remember.get() and self.var_key.get().strip():
            data["api_key"] = self.var_key.get().strip()
        ap.save_settings(data)

    def _on_close(self):
        self.stop_flag.set()
        self._save_settings()
        self.destroy()

    def _start(self):
        if not self.inputs:
            messagebox.showwarning(ap.APP_TITLE, "Adicione uma pasta ou arquivos primeiro.")
            return
        engine = ENGINES[self.var_eng.get()]
        if engine == "claude" and not self.var_key.get().strip():
            messagebox.showwarning(ap.APP_TITLE, "Informe a chave de API do Claude ou escolha o Google.")
            return
        out = self.var_out.get().strip()
        if not out:
            first = Path(self.inputs[0])
            out = str((first if first.is_dir() else first.parent) / "traduzido")
            self.var_out.set(out)

        cfg = mt.Config(
            source_lang=self.src_langs[self.var_src.get()], target_lang=TARGET_LANGS[self.var_dst.get()],
            engine=engine, api_key=self.var_key.get().strip() or None,
            font=self.var_font.get().strip() or None, uppercase=self.var_upper.get(),
            gpu=None if self.var_gpu.get() else False, debug=self.var_dbg.get(),
        )
        self._save_settings()
        self.stop_flag.clear()
        self.progress["value"] = 0
        self.btn_go.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_open.configure(state="disabled")
        threading.Thread(target=self._work, args=(cfg, list(self.inputs), out, self.var_cbz.get()),
                         daemon=True).start()

    # ── thread de trabalho ──────────────────────────────────────────────────
    def _work(self, cfg, inputs, out, make_cbz):
        try:
            pipe = mt.Pipeline(cfg, log=lambda m: self.q.put(("log", m)))
            if not pipe.font_path:
                self.q.put(("log", "Aviso: nenhuma fonte encontrada. Escolha um .ttf no campo 'Fonte'."))

            def progress(i, n, dst):
                self.q.put(("progress", i, n))
                self.q.put(("preview", str(dst)))

            n = pipe.run(inputs, out, progress=progress, should_stop=self.stop_flag.is_set)
            if make_cbz and n:
                self.q.put(("log", f"CBZ criado: {mt.make_cbz(Path(out))}"))
            self.q.put(("done", f"Concluído: {n} imagem(ns) em {out}"))
        except Exception as e:
            import logging
            logging.exception("Falha ao traduzir")
            self.q.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                kind, *data = self.q.get_nowait()
                if kind == "log":
                    self._write_log(data[0])
                elif kind == "progress":
                    self.progress["maximum"], self.progress["value"] = data[1], data[0]
                elif kind == "preview":
                    self._show_preview(data[0])
                elif kind in ("done", "error"):
                    self._write_log(data[0] if kind == "done" else f"ERRO: {data[0]}")
                    self.btn_go.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.btn_open.configure(state="normal" if kind == "done" else "disabled")
                    if kind == "error":
                        messagebox.showerror(ap.APP_TITLE, data[0])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _show_preview(self, path: str):
        try:
            im = Image.open(path).convert("RGB")
            if im.height > im.width * 1.6:          # tira vertical: mostra só o topo
                im = im.crop((0, 0, im.width, int(im.width * 1.6)))
            im.thumbnail((PREVIEW_W, PREVIEW_H))
            self._photo = ImageTk.PhotoImage(im)
            self.preview.configure(image=self._photo, text="")
        except Exception as e:
            self._write_log(f"(prévia indisponível: {e})")


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
