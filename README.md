# Traducteur PDF anglais → français

Ce petit logiciel extrait le texte d'un fichier PDF anglais avec PyMuPDF et utilise Tesseract OCR pour les pages scannées ou pour conserver des indices de mise en page, traduit le texte en français via l'API DeepL, puis reconstruit avec ReportLab un nouveau PDF contenant le texte traduit.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Installez aussi le binaire Tesseract OCR sur votre système.
# Exemple Ubuntu/Debian : sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

## Essayer le logiciel sans clé DeepL

Après l'installation des dépendances, vous pouvez lancer un essai local qui crée un PDF anglais de démonstration puis génère un PDF français de démonstration sans appeler DeepL :

```bash
python pdf_translator_fr.py --demo
```

Les fichiers sont créés dans `demo_output/` :

- `demo_anglais.pdf` : PDF d'entrée généré pour l'essai.
- `demo_francais.pdf` : PDF de sortie reconstruit par le logiciel.

Ce mode sert uniquement à vérifier l'installation, l'extraction PDF et la reconstruction PDF. Pour une vraie traduction, utilisez une clé API DeepL.

## Utilisation en ligne de commande

```bash
python pdf_translator_fr.py document_anglais.pdf document_francais.pdf \
  --auth-key votre_cle_api_deepl
```

Par défaut, l'application utilise le point d'accès gratuit `https://api-free.deepl.com`. Pour un compte DeepL Pro, utilisez `https://api.deepl.com` avec `--endpoint` :

```bash
python pdf_translator_fr.py document_anglais.pdf document_francais.pdf \
  --endpoint https://api.deepl.com \
  --auth-key votre_cle_api_deepl
```

Options OCR utiles :

```bash
# auto = utilise PyMuPDF puis Tesseract seulement si aucun texte n'est détecté
# always = force Tesseract OCR pour toutes les pages
# never = désactive Tesseract OCR
python pdf_translator_fr.py scan.pdf scan_fr.pdf --auth-key votre_cle_api_deepl --ocr-mode always --ocr-lang eng
```

Vous pouvez aussi configurer ces valeurs par variables d'environnement :

```bash
export DEEPL_ENDPOINT="https://api-free.deepl.com"
export DEEPL_API_KEY="votre_cle_api_deepl"
python pdf_translator_fr.py document_anglais.pdf document_francais.pdf
```

## Interface utilisateur Tkinter

Pour lancer l'interface utilisateur Tkinter avec sélection de fichier, clé DeepL, langues et options OCR :

```bash
python pdf_translator_fr.py --gui
```

L'interface Tkinter permet de choisir le PDF anglais, le chemin du PDF français, l'endpoint DeepL, la clé API, les langues source/cible, le mode OCR Tesseract, la langue OCR et la résolution DPI.

## Fichier EXE Windows téléchargeable

Le projet contient une configuration PyInstaller pour compiler l'application Tkinter en fichier `TraducteurPDF_FR.exe`.

### Compilation locale sous Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build_windows_exe.ps1
```

L'exécutable est créé dans `dist\TraducteurPDF_FR.exe`.

### Téléchargement depuis GitHub Actions

Le workflow `Build Windows EXE` compile automatiquement l'exécutable Windows et publie un artefact téléchargeable nommé `TraducteurPDF_FR-windows-exe`. Lancez le workflow manuellement depuis l'onglet **Actions**, puis téléchargez l'artefact généré.

> Note : l'exécutable contient l'application Python, mais Tesseract OCR doit toujours être installé sur Windows si vous utilisez les options OCR.

## Limites

- Les PDF scannés sont traités avec Tesseract OCR, mais la qualité dépend de la résolution du scan et des langues Tesseract installées.
- La mise en page originale n'est pas reproduite à l'identique : Tesseract OCR conserve des indices de lignes/indentations, puis ReportLab reconstruit un PDF texte simple.
- La qualité, les coûts et les limites de volume dépendent de votre compte DeepL API.
