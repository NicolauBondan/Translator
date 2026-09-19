#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manhua Translator
=================
Lê páginas de manhua (também funciona com mangá e manhwa), detecta o texto com
OCR, traduz e escreve a tradução diretamente sobre a imagem.

Pipeline
    1. OCR (RapidOCR; EasyOCR p/ japonês e coreano) em fatias, para suportar tiras verticais gigantes (webtoon)
    2. Agrupa as linhas detectadas em "balões" (uma fala = um balão)
    3. Traduz tudo de uma vez (Google grátis ou Claude, com contexto)
    4. Apaga o texto original (preenche o fundo ou usa inpainting)
    5. Escreve o texto traduzido, ajustando fonte e quebra de linha ao balão

Uso rápido (linha de comando):
    python manhua_translator.py capitulo_01/ -o traduzido
    python manhua_translator.py pagina.jpg capitulo.cbz --engine claude
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app_paths import is_frozen, resource_dir, user_dir

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
Box = Tuple[int, int, int, int]

LANG_NAMES = {
    "pt": "português do Brasil",
    "en": "inglês",
    "es": "espanhol",
    "fr": "francês",
}


# ════════════════════════════════════════════════════════════════════════════
# Configuração e tipos
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Config:
    source_lang: str = "ch_sim"          # ch_sim | ch_tra | ja | ko | en
    ocr_engine: str = "auto"             # auto | rapidocr | easyocr
    target_lang: str = "pt"
    engine: str = "google"               # google | claude
    claude_model: str = "claude-sonnet-5"
    api_key: Optional[str] = None
    glossary: Dict[str, str] = field(default_factory=dict)
    font: Optional[str] = None
    uppercase: bool = True
    gpu: Optional[bool] = None           # None = detectar automaticamente
    min_conf: float = 0.25               # confiança mínima do OCR
    merge_factor: float = 0.7            # quão perto duas linhas precisam estar para virar o mesmo balão
    chunk_overlap: int = 120             # sobreposição entre fatias (px)
    ignore_regex: str = r"(https?://|www\.|\.com\b|\.cn\b|\.net\b)"  # marcas d'água
    debug: bool = False                  # salva imagem com as caixas detectadas


@dataclass
class Detection:
    box: Box
    text: str
    conf: float


@dataclass
class Region:
    dets: List[Detection]
    box: Box
    text: str
    font_size: float
    vertical: bool = False
    translated: str = ""
    uniform: bool = False                        # fundo liso (balão) ou arte?
    bg_bgr: Tuple[int, int, int] = (255, 255, 255)
    text_bgr: Optional[Tuple[int, int, int]] = None
    area: Box = (0, 0, 0, 0)                     # onde o texto traduzido será escrito


# ════════════════════════════════════════════════════════════════════════════
# Geometria
# ════════════════════════════════════════════════════════════════════════════
def _area(b) -> float:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _containment(a, b) -> float:
    m = min(_area(a), _area(b))
    return _inter(a, b) / m if m > 0 else 0.0


def _union(boxes) -> Box:
    return (
        int(min(b[0] for b in boxes)),
        int(min(b[1] for b in boxes)),
        int(max(b[2] for b in boxes)),
        int(max(b[3] for b in boxes)),
    )


def _expand(b, e) -> Tuple[float, float, float, float]:
    return (b[0] - e, b[1] - e, b[2] + e, b[3] + e)


def _clip(b, w: int, h: int) -> Box:
    return (
        max(0, int(math.floor(b[0]))),
        max(0, int(math.floor(b[1]))),
        min(w, int(math.ceil(b[2]))),
        min(h, int(math.ceil(b[3]))),
    )


def _lum(bgr) -> float:
    return 0.114 * bgr[0] + 0.587 * bgr[1] + 0.299 * bgr[2]


# ════════════════════════════════════════════════════════════════════════════
# E/S de imagens (compatível com caminhos com acento no Windows)
# ════════════════════════════════════════════════════════════════════════════
def imread(path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Não foi possível abrir a imagem: {path}")
    return img


def imsave(pil: Image.Image, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        pil.save(dst, quality=95, subsampling=0)
    else:
        pil.save(dst)


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ════════════════════════════════════════════════════════════════════════════
# 1) OCR
# ════════════════════════════════════════════════════════════════════════════
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def rapidocr_available() -> bool:
    return is_frozen() or _has_module("rapidocr_onnxruntime") or _has_module("rapidocr")


def easyocr_available() -> bool:
    return not is_frozen() and _has_module("easyocr")


class RapidOCREngine:
    """OCR com RapidOCR (modelos PP-OCR em ONNX): leve, offline e ótimo para chinês.

    Os modelos vêm dentro do próprio pacote — não baixa nada."""

    def __init__(self):
        self._new_api = False
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            try:
                from rapidocr import RapidOCR   # pacote novo (API diferente)
                self._new_api = True
            except ImportError as e:
                raise RuntimeError("RapidOCR não está instalado. Rode:  pip install -r requirements.txt") from e
        self.engine = RapidOCR()

    def detect(self, img_bgr: np.ndarray) -> List[Detection]:
        if self._new_api:
            res = self.engine(img_bgr, use_cls=False)
            if getattr(res, "boxes", None) is None:
                return []
            triples = list(zip(res.boxes, res.txts, res.scores))
        else:
            result, _ = self.engine(img_bgr, use_cls=False)
            triples = result or []
        out = []
        for pts, text, conf in triples:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            out.append(Detection((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                                 str(text), float(conf)))
        return out


class EasyOCREngine:
    """OCR com EasyOCR (japonês, coreano...). Só na versão de código: baixa modelos (~100 MB)."""

    def __init__(self, lang: str = "ch_sim", gpu: Optional[bool] = None):
        try:
            import easyocr
        except ImportError as e:
            raise RuntimeError(
                "Este idioma precisa do EasyOCR, que não está instalado. Rode:  pip install easyocr"
            ) from e
        if gpu is None:
            try:
                import torch
                gpu = bool(torch.cuda.is_available())
            except Exception:
                gpu = False
        langs = [lang] if lang == "en" else [lang, "en"]
        self.reader = easyocr.Reader(langs, gpu=gpu, verbose=False)

    def detect(self, img_bgr: np.ndarray) -> List[Detection]:
        out = []
        for pts, text, conf in self.reader.readtext(
            img_bgr, paragraph=False, min_size=12, text_threshold=0.6, low_text=0.3
        ):
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            out.append(Detection((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                                 str(text), float(conf)))
        return out


def make_ocr(cfg: "Config"):
    """RapidOCR para chinês/inglês (padrão); EasyOCR para japonês/coreano."""
    prefer = cfg.ocr_engine
    if prefer == "auto":
        use_rapid = cfg.source_lang in ("ch_sim", "ch_tra", "en") and rapidocr_available()
        prefer = "rapidocr" if use_rapid else "easyocr"
    return RapidOCREngine() if prefer == "rapidocr" else EasyOCREngine(cfg.source_lang, cfg.gpu)


def chunk_ranges(h: int, w: int, overlap: int) -> List[Tuple[int, int]]:
    """Divide imagens muito altas em fatias (o OCR perde qualidade em tiras gigantes)."""
    chunk = int(min(max(w * 1.6, 1200), 2200))
    if h <= chunk * 1.25:
        return [(0, h)]
    ranges, y = [], 0
    while True:
        y2 = min(h, y + chunk)
        ranges.append((y, y2))
        if y2 >= h:
            break
        y = y2 - overlap
    return ranges


def dedupe(dets: List[Detection]) -> List[Detection]:
    """Remove detecções repetidas na zona de sobreposição entre fatias."""
    kept: List[Detection] = []
    for d in sorted(dets, key=lambda d: -_area(d.box)):
        if any(_containment(d.box, k.box) > 0.6 for k in kept):
            continue
        kept.append(d)
    return kept


def detect_page(ocr, img: np.ndarray, cfg: Config) -> List[Detection]:
    h, w = img.shape[:2]
    dets: List[Detection] = []
    for y1, y2 in chunk_ranges(h, w, cfg.chunk_overlap):
        for d in ocr.detect(img[y1:y2]):
            x1, a, x2, b = d.box
            dets.append(Detection((x1, a + y1, x2, b + y1), d.text, d.conf))
    return dedupe(dets)


def filter_dets(dets: List[Detection], cfg: Config) -> List[Detection]:
    ignore = re.compile(cfg.ignore_regex, re.I) if cfg.ignore_regex else None
    out = []
    for d in dets:
        t = d.text.strip()
        if d.conf < cfg.min_conf or not t or not re.search(r"\w", t):
            continue
        if ignore and ignore.search(t):
            continue
        out.append(d)
    return out


# ════════════════════════════════════════════════════════════════════════════
# 2) Agrupamento em balões
# ════════════════════════════════════════════════════════════════════════════
def _should_merge(a: Box, b: Box, k: float) -> bool:
    fs = max(1, min(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]))
    vgap = max(a[1], b[1]) - min(a[3], b[3])   # < 0 → sobrepõem na vertical
    hgap = max(a[0], b[0]) - min(a[2], b[2])   # < 0 → sobrepõem na horizontal
    # linhas empilhadas, uma abaixo da outra
    if vgap <= k * fs and hgap < 0:
        overlap = -hgap / max(1, min(a[2] - a[0], b[2] - b[0]))
        if overlap > 0.2:
            return True
    # lado a lado (pedaços da mesma linha ou colunas verticais)
    if vgap < -0.3 * fs and hgap <= k * fs:
        return True
    return False


def _reading_order(members: List[Detection], fs: float) -> List[Detection]:
    rows: List[list] = []
    for d in sorted(members, key=lambda d: (d.box[1] + d.box[3]) / 2):
        cy = (d.box[1] + d.box[3]) / 2
        if rows and abs(cy - rows[-1][0]) < 0.5 * fs:
            rows[-1][1].append(d)
        else:
            rows.append([cy, [d]])
    return [d for _, r in rows for d in sorted(r, key=lambda d: d.box[0])]


def _join(texts: Sequence[str]) -> str:
    out = ""
    for t in (s.strip() for s in texts):
        if out and re.search(r"[A-Za-z0-9,.!?]$", out) and re.match(r"[A-Za-z0-9]", t):
            out += " "
        out += t
    return out


def _make_region(members: List[Detection]) -> Region:
    fs = max(8.0, float(np.median([min(d.box[2] - d.box[0], d.box[3] - d.box[1]) for d in members])))
    vertical = sum((d.box[3] - d.box[1]) > 1.5 * (d.box[2] - d.box[0]) for d in members) > len(members) / 2
    if vertical:  # colunas lidas da direita para a esquerda
        ordered = sorted(members, key=lambda d: -(d.box[0] + d.box[2]) / 2)
    else:
        ordered = _reading_order(members, fs)
    return Region(dets=ordered, box=_union([d.box for d in ordered]),
                  text=_join([d.text for d in ordered]), font_size=fs, vertical=vertical)


def group_regions(dets: List[Detection], cfg: Config) -> List[Region]:
    n = len(dets)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _should_merge(dets[i].box, dets[j].box, cfg.merge_factor):
                parent[find(i)] = find(j)
    groups: Dict[int, List[Detection]] = {}
    for i, d in enumerate(dets):
        groups.setdefault(find(i), []).append(d)
    regions = [_make_region(m) for m in groups.values()]
    regions.sort(key=lambda r: (r.box[1], r.box[0]))
    return regions


# ════════════════════════════════════════════════════════════════════════════
# 3) Tradução
# ════════════════════════════════════════════════════════════════════════════
class GoogleTranslator:
    """Google Tradutor via deep-translator (grátis, sem chave)."""

    def __init__(self, target: str = "pt"):
        try:
            from deep_translator import GoogleTranslator as _G
        except ImportError as e:
            raise RuntimeError("Instale:  pip install deep-translator") from e
        self._t = _G(source="auto", target=target)

    def translate(self, texts: List[str]) -> List[str]:
        out = []
        for t in texts:
            for attempt in range(3):
                try:
                    out.append((self._t.translate(t) or "").strip())
                    break
                except Exception:
                    time.sleep(1 + attempt)
            else:
                out.append("")
        return out


def _parse_json_list(text: str):
    text = re.sub(r"```(?:json)?", "", text)
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < 0:
        raise ValueError("resposta sem JSON")
    return json.loads(text[a:b + 1])


class ClaudeTranslator:
    """Tradução com Claude: entende contexto, corrige erros de OCR e mantém o tom."""

    def __init__(self, api_key: Optional[str], model: str, target: str = "pt",
                 glossary: Optional[Dict[str, str]] = None):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("Instale:  pip install anthropic") from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("Informe a chave da API (--api-key ou variável ANTHROPIC_API_KEY).")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model
        gloss = ""
        if glossary:
            gloss = "\nGlossário obrigatório (mantenha exatamente): " + "; ".join(
                f"{k} → {v}" for k, v in glossary.items())
        self.system = (
            f"Você é tradutor profissional de quadrinhos (manhua, mangá, manhwa) para "
            f"{LANG_NAMES.get(target, target)}. Receberá falas extraídas por OCR de uma página, "
            "em ordem de leitura, como JSON: [{\"id\":0,\"texto\":\"...\"}].\n"
            "Regras:\n"
            "1. Traduza de forma natural e CURTA, adequada a balões de fala; preserve tom, "
            "gírias, formalidade e emoção.\n"
            "2. O OCR pode conter erros: corrija pelo contexto.\n"
            "3. Onomatopeias: use um equivalente curto no idioma de destino.\n"
            "4. Se o item for ruído, marca d'água, URL ou não for texto real, devolva traducao vazia.\n"
            "5. Não explique nada. Responda SOMENTE com um array JSON "
            "[{\"id\":0,\"traducao\":\"...\"}], um objeto por item." + gloss
        )
        self.history: List[dict] = []

    def translate(self, texts: List[str]) -> List[str]:
        results: List[str] = []
        for start in range(0, len(texts), 50):
            results += self._batch(texts[start:start + 50])
        return results

    def _batch(self, batch: List[str]) -> List[str]:
        payload = [{"id": i, "texto": t} for i, t in enumerate(batch)]
        user = ""
        if self.history:
            user += ("Contexto (falas anteriores já traduzidas, só para referência):\n"
                     + json.dumps(self.history[-10:], ensure_ascii=False) + "\n\n")
        user += "Traduza estas falas:\n" + json.dumps(payload, ensure_ascii=False)
        last: Exception = RuntimeError("desconhecido")
        for attempt in range(3):
            try:
                resp = self.client.messages.create(
                    model=self.model, max_tokens=4096, system=self.system,
                    messages=[{"role": "user", "content": user}])
                raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                by_id = {int(x["id"]): str(x.get("traducao", "")).strip() for x in _parse_json_list(raw)}
                out = [by_id.get(i, "") for i in range(len(batch))]
                self.history = (self.history + [{"original": s, "traducao": t}
                                                for s, t in zip(batch, out) if t])[-30:]
                return out
            except Exception as e:  # rede, JSON inválido, limite de taxa...
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Falha ao traduzir com Claude: {last}")


def make_translator(cfg: Config):
    if cfg.engine == "claude":
        return ClaudeTranslator(cfg.api_key, cfg.claude_model, cfg.target_lang, cfg.glossary)
    return GoogleTranslator(cfg.target_lang)


# ════════════════════════════════════════════════════════════════════════════
# 4) Limpeza do texto original
# ════════════════════════════════════════════════════════════════════════════
def _stroke_mask(gray: np.ndarray) -> np.ndarray:
    """Pixels de traço do texto = classe minoritária do limiar de Otsu."""
    if gray.size == 0 or gray.std() < 4:
        return np.zeros(gray.shape, np.uint8)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    white = int((th == 255).sum())
    minority = 255 if white < th.size - white else 0
    return ((th == minority) * 255).astype(np.uint8)


def _estimate_text_color(img: np.ndarray, region: Region):
    h, w = img.shape[:2]
    cols = []
    for d in region.dets:
        x1, y1, x2, y2 = _clip(d.box, w, h)
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        m = _stroke_mask(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)) > 0
        if m.sum() > 10:
            cols.append(np.median(roi[m], axis=0))
    if not cols:
        return None
    return tuple(int(v) for v in np.median(cols, axis=0))


def _inpaint_text(img: np.ndarray, box: Box, fs: int) -> None:
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return
    mask = _stroke_mask(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY))
    k = max(3, (fs // 5) | 1)
    mask = cv2.dilate(mask, np.ones((k, k), np.uint8))
    pad = max(4, fs // 2)
    px1, py1, px2, py2 = _clip((x1 - pad, y1 - pad, x2 + pad, y2 + pad), W, H)
    crop = img[py1:py2, px1:px2].copy()
    full = np.zeros(crop.shape[:2], np.uint8)
    full[y1 - py1:y2 - py1, x1 - px1:x2 - px1] = mask
    img[py1:py2, px1:px2] = cv2.inpaint(crop, full, 3, cv2.INPAINT_TELEA)


def clean_region(img: np.ndarray, region: Region) -> None:
    """Apaga o texto original (in-place).

    Se o fundo ao redor é liso (balão), preenche com a cor do fundo — resultado
    perfeito. Se é arte, usa inpainting só nos traços das letras.
    """
    H, W = img.shape[:2]
    fs = max(6, int(region.font_size))
    e = max(2, int(fs * 0.18))
    r = max(4, int(fs * 0.35))
    cb = _clip(_expand(region.box, e), W, H)
    ob = _clip(_expand(cb, r), W, H)
    outer = img[ob[1]:ob[3], ob[0]:ob[2]]
    m = np.ones(outer.shape[:2], bool)
    m[cb[1] - ob[1]:cb[3] - ob[1], cb[0] - ob[0]:cb[2] - ob[0]] = False
    ring = outer[m].astype(np.int16)

    region.text_bgr = _estimate_text_color(img, region)
    uniform = False
    if len(ring) >= 40:
        med = np.median(ring, axis=0)
        uniform = (np.abs(ring - med).max(axis=1) < 30).mean() > 0.9
        region.bg_bgr = tuple(int(v) for v in med)
    else:
        region.bg_bgr = (255, 255, 255)

    if uniform:
        color = np.array(region.bg_bgr, np.uint8)
        for d in region.dets:
            x1, y1, x2, y2 = _clip(_expand(d.box, e), W, H)
            img[y1:y2, x1:x2] = color
    else:
        for d in region.dets:
            _inpaint_text(img, _clip(_expand(d.box, e), W, H), fs)
    region.uniform = uniform


# ════════════════════════════════════════════════════════════════════════════
# 5) Área do balão e escrita do texto traduzido
# ════════════════════════════════════════════════════════════════════════════
def find_bubble(img: np.ndarray, region: Region):
    """Acha o balão (área conectada da cor de fundo) que contém a fala.

    Retorna (caixa_do_balão, taxa_de_preenchimento) ou None se o "balão"
    vaza para o resto da página (fundo aberto)."""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = region.box
    mx, my = int((x2 - x1) * 1.5) + 40, int((y2 - y1) * 1.5) + 40
    rx1, ry1, rx2, ry2 = max(0, x1 - mx), max(0, y1 - my), min(W, x2 + mx), min(H, y2 + my)
    roi = img[ry1:ry2, rx1:rx2]
    bg = np.array(region.bg_bgr, np.int16)
    cand = (np.abs(roi.astype(np.int16) - bg).max(axis=2) < 30).astype(np.uint8)
    _, labels = cv2.connectedComponents(cand, connectivity=4)
    cx, cy = (x1 + x2) // 2 - rx1, (y1 + y2) // 2 - ry1
    lab = labels[min(max(cy, 0), labels.shape[0] - 1), min(max(cx, 0), labels.shape[1] - 1)]
    if lab == 0:
        return None
    ys, xs = np.where(labels == lab)
    bx1, bx2, by1, by2 = xs.min(), xs.max(), ys.min(), ys.max()
    if bx1 == 0 or by1 == 0 or bx2 >= labels.shape[1] - 1 or by2 >= labels.shape[0] - 1:
        return None  # tocou a borda da janela → não é um balão fechado
    fill = len(xs) / float((bx2 - bx1 + 1) * (by2 - by1 + 1))
    return (bx1 + rx1, by1 + ry1, bx2 + rx1, by2 + ry1), fill


def compute_area(img: np.ndarray, region: Region) -> Box:
    H, W = img.shape[:2]
    x1, y1, x2, y2 = region.box
    if region.uniform:
        found = find_bubble(img, region)
        if found:
            (bx1, by1, bx2, by2), fill = found
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            k = 0.9 if fill > 0.9 else 0.74   # retângulo vs. elipse
            hw = min(cx - bx1, bx2 - cx) * k
            hh = min(cy - by1, by2 - cy) * k
            area = (cx - hw, cy - hh, cx + hw, cy + hh)
            return _clip(_union([area, region.box]), W, H)
    ex = (x2 - x1) * 0.15 + region.font_size * 0.3
    ey = (y2 - y1) * 0.15 + region.font_size * 0.3
    return _clip((x1 - ex, y1 - ey, x2 + ex, y2 + ey), W, H)


FONT_CANDIDATES = [
    "C:/Windows/Fonts/comicbd.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def find_font(user_font: Optional[str] = None) -> Optional[str]:
    """Fonte escolhida → .ttf/.otf em <pasta do usuário>/fonts → fonts/ do app → fontes do sistema."""
    if user_font and Path(user_font).is_file():
        return str(user_font)
    for folder in (user_dir() / "fonts", resource_dir() / "fonts"):
        if folder.is_dir():
            for p in sorted(list(folder.glob("*.ttf")) + list(folder.glob("*.otf"))):
                return str(p)
    return next((p for p in FONT_CANDIDATES if os.path.isfile(p)), None)


@lru_cache(maxsize=256)
def load_font(path: Optional[str], size: int):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def wrap_text(text: str, measure: Callable[[str], float], max_w: float) -> List[str]:
    lines: List[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            while measure(word) > max_w and len(word) > 1:   # palavra maior que a linha: hifeniza
                k = len(word)
                while k > 1 and measure(word[:k] + "-") > max_w:
                    k -= 1
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:k] + "-")
                word = word[k:]
            test = word if not cur else cur + " " + word
            if measure(test) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines or [""]


def _balance(text, measure, lines, max_w):
    """Estreita o bloco de texto mantendo o nº de linhas → visual de balão."""
    n = len(lines)
    if n <= 1:
        return lines
    best = lines
    w = max(measure(l) for l in lines)
    hyph = lambda ls: sum(l.endswith("-") for l in ls)
    for _ in range(12):
        cand = wrap_text(text, measure, w * 0.93)
        if len(cand) > n or hyph(cand) > hyph(best):
            break
        best, w = cand, max(measure(l) for l in cand)
    return best


def layout_text(text: str, font_path: Optional[str], max_w: float, max_h: float, lo: int, hi: int):
    """Maior tamanho de fonte em que o texto cabe na área. → (tamanho, fonte, linhas, altura_linha)"""
    def build(size: int):
        font = load_font(font_path, size)
        measure = font.getlength
        lines = wrap_text(text, measure, max_w)
        return font, measure, lines, size * 1.12

    hi = max(hi, lo)
    best, a, b = None, lo, hi
    while a <= b:
        mid = (a + b) // 2
        font, measure, lines, lh = build(mid)
        if len(lines) * lh <= max_h and max(measure(l) for l in lines) <= max_w + 1:
            best, a = (mid, font, measure, lines, lh), mid + 1
        else:
            b = mid - 1
    if best is None:
        font, measure, lines, lh = build(lo)
        best = (lo, font, measure, lines, lh)
    size, font, measure, lines, lh = best
    return size, font, _balance(text, measure, lines, max_w), lh


def draw_region(draw: ImageDraw.ImageDraw, r: Region, cfg: Config, font_path: Optional[str]) -> None:
    text = r.translated.upper() if cfg.uppercase else r.translated
    x1, y1, x2, y2 = r.area
    aw, ah = max(10, x2 - x1), max(10, y2 - y1)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    size, font, lines, lh = layout_text(text, font_path, aw, ah, 9, int(max(12, min(r.font_size * 1.3, ah))))

    if r.uniform:   # balão: preto sobre fundo claro, branco sobre fundo escuro
        fill = (0, 0, 0) if _lum(r.bg_bgr) >= 128 else (255, 255, 255)
        sw, sc = 0, None
    else:           # texto solto sobre a arte: cor original + contorno contrastante
        tb = r.text_bgr or (255, 255, 255)
        fill = tuple(reversed(tb))
        sw = max(1, size // 10)
        sc = (0, 0, 0) if _lum(tb) >= 128 else (255, 255, 255)

    y = cy - lh * len(lines) / 2 + lh / 2
    for line in lines:
        draw.text((cx, y), line, font=font, fill=fill, anchor="mm", stroke_width=sw, stroke_fill=sc)
        y += lh


# ════════════════════════════════════════════════════════════════════════════
# Pipeline
# ════════════════════════════════════════════════════════════════════════════
def collect_images(inputs: Sequence[str], tmp: str) -> List[Tuple[Path, Path]]:
    """Expande pastas, .zip/.cbz e imagens soltas em [(arquivo, caminho_relativo_de_saída)]."""
    items: List[Tuple[Path, Path]] = []

    def imgs(root: Path):
        return sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
                      key=lambda p: natural_key(str(p.relative_to(root))))

    for inp in map(Path, inputs):
        if inp.is_dir():
            items += [(p, p.relative_to(inp)) for p in imgs(inp)]
        elif inp.suffix.lower() in (".zip", ".cbz"):
            dest = Path(tmp) / inp.stem
            with zipfile.ZipFile(inp) as z:
                z.extractall(dest)
            items += [(p, Path(inp.stem) / p.relative_to(dest)) for p in imgs(dest)]
        elif inp.suffix.lower() in IMAGE_EXTS:
            items.append((inp, Path(inp.name)))
    return items


class Pipeline:
    def __init__(self, cfg: Config, log: Callable[[str], None] = print, ocr=None, translator=None):
        self.cfg, self.log = cfg, log
        self._ocr, self._translator = ocr, translator
        self.font_path = find_font(cfg.font)

    @property
    def ocr(self):
        if self._ocr is None:
            self.log("Carregando o OCR…")
            self._ocr = make_ocr(self.cfg)
        return self._ocr

    @property
    def translator(self):
        if self._translator is None:
            self._translator = make_translator(self.cfg)
        return self._translator

    # ── uma página ──────────────────────────────────────────────────────────
    def process_image(self, src: Path, dst: Path) -> int:
        cfg = self.cfg
        img = imread(src)
        dets = filter_dets(detect_page(self.ocr, img, cfg), cfg)
        regions = group_regions(dets, cfg)
        self.log(f"  {len(regions)} fala(s) encontrada(s)")

        translated = self.translator.translate([r.text for r in regions]) if regions else []
        todo: List[Region] = []
        for r, t in zip(regions, translated):
            t = (t or "").strip()
            if t and t.lower() != r.text.lower():
                r.translated = t
                todo.append(r)

        out = img.copy()
        for r in todo:
            clean_region(out, r)
        for r in todo:
            r.area = compute_area(out, r)

        pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        for r in todo:
            try:
                draw_region(draw, r, cfg, self.font_path)
            except Exception as e:
                self.log(f"  aviso: não consegui escrever uma fala ({e})")

        if dst.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            dst = dst.with_suffix(".png")
        imsave(pil, dst)
        if cfg.debug:
            self._save_debug(img, dets, regions, dst)
        return len(todo)

    def _save_debug(self, img, dets, regions, dst: Path) -> None:
        dbg = img.copy()
        for d in dets:
            cv2.rectangle(dbg, d.box[:2], d.box[2:], (0, 0, 255), 2)
        for r in regions:
            cv2.rectangle(dbg, r.box[:2], r.box[2:], (0, 200, 0), 2)
            if r.area != (0, 0, 0, 0):
                cv2.rectangle(dbg, r.area[:2], r.area[2:], (255, 100, 0), 2)
        cv2.imencode(".png", dbg)[1].tofile(str(dst.with_name(dst.stem + "_debug.png")))

    # ── vários arquivos ─────────────────────────────────────────────────────
    def run(self, inputs: Sequence[str], out_dir: str,
            progress: Optional[Callable[[int, int, Path], None]] = None,
            should_stop: Optional[Callable[[], bool]] = None) -> int:
        out_root = Path(out_dir)
        done = 0
        with tempfile.TemporaryDirectory() as tmp:
            items = collect_images(inputs, tmp)
            if not items:
                raise RuntimeError("Nenhuma imagem encontrada nas entradas informadas.")
            self.log(f"{len(items)} imagem(ns) para processar.")
            for i, (src, rel) in enumerate(items, 1):
                if should_stop and should_stop():
                    self.log("Cancelado.")
                    break
                self.log(f"[{i}/{len(items)}] {rel}")
                t0 = time.time()
                dst = out_root / rel
                try:
                    self.process_image(src, dst)
                    done += 1
                except Exception as e:
                    self.log(f"  ERRO: {e}")
                    continue
                self.log(f"  ok ({time.time() - t0:.1f}s)")
                if progress:
                    final = dst if dst.suffix.lower() in (".jpg", ".jpeg", ".png") else dst.with_suffix(".png")
                    progress(i, len(items), final)
        return done


def make_cbz(folder: Path) -> Path:
    cbz = folder.with_suffix(".cbz")
    files = sorted((p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS
                    and not p.stem.endswith("_debug")), key=lambda p: natural_key(str(p)))
    with zipfile.ZipFile(cbz, "w", zipfile.ZIP_STORED) as z:
        for p in files:
            z.write(p, p.relative_to(folder).as_posix())
    return cbz


# ════════════════════════════════════════════════════════════════════════════
# Linha de comando
# ════════════════════════════════════════════════════════════════════════════
def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Traduz páginas de manhua/mangá/manhwa diretamente na imagem.")
    p.add_argument("inputs", nargs="+", help="imagens, pastas, .zip ou .cbz")
    p.add_argument("-o", "--output", default="traduzido", help="pasta de saída (padrão: traduzido)")
    p.add_argument("--from", dest="source_lang", default="ch_sim",
                   choices=["ch_sim", "ch_tra", "ja", "ko", "en"], help="idioma original (padrão: ch_sim)")
    p.add_argument("--to", dest="target_lang", default="pt", help="idioma de destino (padrão: pt)")
    p.add_argument("--ocr", choices=["auto", "rapidocr", "easyocr"], default="auto",
                   help="motor de OCR (auto: RapidOCR p/ chinês, EasyOCR p/ japonês/coreano)")
    p.add_argument("--engine", choices=["google", "claude"], default="google")
    p.add_argument("--api-key", help="chave da API da Anthropic (ou use ANTHROPIC_API_KEY)")
    p.add_argument("--claude-model", default=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"))
    p.add_argument("--glossary", help="JSON {\"nome original\": \"nome traduzido\"} (só com --engine claude)")
    p.add_argument("--font", help="arquivo .ttf/.otf para o texto traduzido")
    p.add_argument("--no-uppercase", action="store_true", help="não converter o texto para MAIÚSCULAS")
    p.add_argument("--cpu", action="store_true", help="forçar CPU no OCR")
    p.add_argument("--cbz", action="store_true", help="empacotar o resultado em .cbz")
    p.add_argument("--debug", action="store_true", help="salvar imagens *_debug.png com as caixas detectadas")
    a = p.parse_args(argv)

    glossary = {}
    if a.glossary:
        glossary = json.loads(Path(a.glossary).read_text(encoding="utf-8"))
    cfg = Config(source_lang=a.source_lang, ocr_engine=a.ocr, target_lang=a.target_lang, engine=a.engine,
                 claude_model=a.claude_model, api_key=a.api_key, glossary=glossary, font=a.font,
                 uppercase=not a.no_uppercase, gpu=False if a.cpu else None, debug=a.debug)
    pipe = Pipeline(cfg)
    if not pipe.font_path:
        print("Aviso: nenhuma fonte TrueType encontrada. Coloque um .ttf em ./fonts ou use --font.",
              file=sys.stderr)
    try:
        n = pipe.run(a.inputs, a.output)
    except RuntimeError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    print(f"\nConcluído: {n} imagem(ns) em '{a.output}'.")
    if a.cbz:
        print("CBZ:", make_cbz(Path(a.output)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
