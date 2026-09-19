# -*- mode: python ; coding: utf-8 -*-
# Empacotamento com PyInstaller (modo "pasta", o mais rápido para abrir e o ideal para instalador).
#   pyinstaller ManhuaTranslator.spec --noconfirm --clean
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []

# RapidOCR: traz junto os modelos .onnx e o config.yaml do pacote
for pkg in ("rapidocr_onnxruntime",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("certifi")          # certificados HTTPS (Google Tradutor / Claude)
datas += [("fonts", "fonts"), ("assets", "assets")]
hiddenimports += ["pyclipper", "shapely", "shapely.geometry", "yaml", "bs4",
                  "deep_translator", "anthropic", "PIL.ImageTk"]

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # o instalador usa RapidOCR; PyTorch/EasyOCR deixariam o app com GBs a mais
    excludes=["torch", "torchvision", "easyocr", "tensorflow", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ManhuaTranslator",
    debug=False,
    strip=False,
    upx=False,
    console=False,                 # app de janela, sem terminal preto
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ManhuaTranslator",
)
