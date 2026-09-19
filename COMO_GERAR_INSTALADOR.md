# Como gerar o instalador (Setup.exe) do Manhua Translator

O resultado é **um único arquivo `ManhuaTranslator-Setup-1.0.0.exe`**. Quem for usar só precisa dar dois
cliques nele: não precisa instalar Python, nem abrir terminal, nem baixar modelos de OCR.
O instalador cria o atalho no Menu Iniciar (e opcionalmente na Área de Trabalho), tem desinstalador e
**não pede senha de administrador**.

O instalador só pode ser gerado no **Windows**. Escolha um dos dois caminhos:

---

## Caminho A — na nuvem, sem instalar nada (recomendado)

O GitHub gera o instalador para você, de graça.

1. Crie uma conta em **github.com** e clique em **New repository** (pode ser privado). Dê o nome
   `manhua-translator`.
2. Extraia o arquivo `manhua-translator-fonte.zip` no seu computador.
3. No repositório, clique em **Add file → Upload files** e arraste **todo o conteúdo** da pasta extraída
   (inclusive as pastas `assets`, `fonts` e `.github`). Clique em **Commit changes**.
   - Se a pasta oculta `.github` não subir junto: **Add file → Create new file**, digite exatamente
     `.github/workflows/build-windows.yml` no nome e cole o conteúdo do arquivo de mesmo nome.
4. Abra a aba **Actions → "Gerar instalador Windows" → Run workflow**.
5. Espere uns 5 a 10 minutos. Quando ficar verde, abra a execução e baixe **ManhuaTranslator-Setup**
   (em *Artifacts*). Dentro do .zip está o `Setup.exe`.

Para publicar uma versão com link de download público: crie uma **Release** com a tag `v1.0.0`.
O instalador será anexado nela automaticamente.

---

## Caminho B — no seu próprio PC Windows

1. Instale o **Python 3.12** (python.org), marcando **"Add python.exe to PATH"**.
2. Instale o **Inno Setup 6** (jrsoftware.org/isdl.php).
3. Extraia o `.zip`, entre na pasta e dê **dois cliques em `build_windows.bat`**.
4. Aguarde (10–20 min na primeira vez). O instalador aparece em `installer_output\`.

---

## Depois de gerar

- **Teste em outro PC** (ou numa máquina virtual) sem Python instalado antes de distribuir.
- **Aviso azul do Windows ("O Windows protegeu seu computador")**: acontece com qualquer programa novo
  sem assinatura digital. O usuário clica em *Mais informações → Executar assim mesmo*. Para eliminar o
  aviso é preciso comprar um certificado de assinatura de código (pago).
- **Nova versão**: mude `APP_VERSION` em `app_paths.py` e gere de novo. Instalar por cima atualiza o app.
- **Fonte de quadrinhos**: coloque um `.ttf` com acentos em `fonts/` **antes** de gerar. Use só fontes cuja
  licença permita redistribuição (ex.: licença OFL). Sem isso o app usa Comic Sans/Arial do Windows.
- **Se o build falhar**: na janela do `.bat` ou no log do GitHub Actions, procure a primeira linha com
  `ERROR`. Erros de "módulo não encontrado" se resolvem adicionando o nome em `hiddenimports` no
  `ManhuaTranslator.spec`. Se o app instalado abrir e fechar sozinho, veja o arquivo
  `%LOCALAPPDATA%\ManhuaTranslator\log.txt`.

## O que vai dentro do instalador

| Parte | Função |
|---|---|
| `launcher.py` → `ManhuaTranslator.exe` | ponto de entrada: log de erros, tela nítida, aviso em caso de falha |
| `gui.py` | a janela do programa |
| `manhua_translator.py` | OCR, tradução, limpeza e escrita do texto |
| RapidOCR + modelos ONNX | leitura do texto (chinês/inglês), 100% offline |
| Python + bibliotecas | embutidos, o usuário não instala nada |

Tamanho esperado do instalador: em torno de 100–150 MB.
