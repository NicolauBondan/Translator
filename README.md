# Manhua Translator

Lê páginas de manhua, detecta o texto, traduz e **escreve a tradução direto na imagem**.

## Para usuários

Baixe e execute `ManhuaTranslator-Setup-x.y.z.exe`. Depois é só abrir **Manhua Translator** no Menu Iniciar:
**+ Pasta → Traduzir**. As páginas traduzidas ficam numa pasta `traduzido`.

Para gerar o instalador, veja **COMO_GERAR_INSTALADOR.md**.

## Para desenvolvedores

```bash
pip install -r requirements.txt
python launcher.py                              # abre a interface (como o app instalado)
python manhua_translator.py cap/ -o traduzido   # linha de comando
python manhua_translator.py cap/ --engine claude --api-key sk-…
python manhua_translator.py cap/ --debug        # salva *_debug.png com as caixas detectadas
```

Japonês/coreano: `pip install easyocr` e use `--from ja` / `--from ko` (não faz parte do instalador).

### Como funciona

1. **OCR** (RapidOCR) em fatias, para suportar tiras verticais gigantes.
2. Linhas agrupadas em **balões**; cada balão vira uma fala.
3. **Tradução** (Google grátis ou Claude, com contexto e glossário).
4. **Limpeza**: fundo liso é repintado; sobre a arte usa-se inpainting só nos traços.
5. **Escrita** do texto ajustando fonte e quebras ao formato do balão.

### Arquivos

| Arquivo | Função |
|---|---|
| `launcher.py` | ponto de entrada do app instalado |
| `gui.py` | interface gráfica (Tkinter) |
| `manhua_translator.py` | motor + linha de comando |
| `app_paths.py` | versão, pastas do usuário, configurações |
| `ManhuaTranslator.spec` | empacotamento PyInstaller |
| `installer.iss` | script do instalador (Inno Setup) |
| `build_windows.bat` | gera o instalador localmente |
| `.github/workflows/build-windows.yml` | gera o instalador na nuvem |

### Ajustes de qualidade

- Motor **Claude** costuma traduzir melhor; `--glossary nomes.json` fixa nomes de personagens.
- Falas juntas/separadas demais: ajuste `merge_factor` em `Config` (padrão 0,7) e use `--debug`.
- Marcas d'água com URL são ignoradas (`ignore_regex`).

### Limitações

- O OCR erra em fontes muito estilizadas, texto girado e onomatopeias desenhadas na arte.
- Balões sem contorno fechado ou com degradê usam o modo "texto sobre a arte" (com contorno).
- Confira o resultado antes de publicar e respeite os direitos autorais da obra.
