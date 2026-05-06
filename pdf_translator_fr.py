#!/usr/bin/env python3
"""Translate English PDF files to French PDFs using DeepL API."""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

DEFAULT_ENDPOINT = "https://api-free.deepl.com"
DEFAULT_MAX_CHARS = 3500


class TranslationError(RuntimeError):
    """Raised when the translation service returns an error."""


@dataclass
class OCRLine:
    """Text and bounding box for a line detected by Tesseract OCR."""

    text: str
    left: int
    top: int
    width: int
    height: int


@dataclass
class DeepLClient:
    """Small client for the DeepL text translation API."""

    endpoint: str = DEFAULT_ENDPOINT
    auth_key: str | None = None
    timeout: int = 60

    def translate(self, text: str, source: str = "EN", target: str = "FR") -> str:
        """Translate a single text chunk with DeepL API."""
        if not text.strip():
            return text
        if not self.auth_key:
            raise TranslationError(
                "Une clé API DeepL est requise. Définissez DEEPL_API_KEY ou utilisez --auth-key."
            )

        import requests

        url = self.endpoint.rstrip("/") + "/v2/translate"
        payload = {
            "text": [text],
            "target_lang": target.upper(),
        }
        if source:
            payload["source_lang"] = source.upper()

        headers = {
            "Authorization": f"DeepL-Auth-Key {self.auth_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TranslationError(f"Impossible de contacter DeepL API: {exc}") from exc

        if response.status_code >= 400:
            raise TranslationError(
                f"Erreur DeepL API ({response.status_code}): {response.text}"
            )

        data = response.json()
        translations = data.get("translations")
        if not isinstance(translations, list) or not translations:
            raise TranslationError("Réponse DeepL invalide: champ 'translations' absent.")

        translated = translations[0].get("text")
        if not isinstance(translated, str):
            raise TranslationError("Réponse DeepL invalide: texte traduit absent.")
        return translated


class DemoTranslationClient:
    """Offline demo translator so users can try the workflow without a DeepL key."""

    replacements = {
        "English": "anglais",
        "French": "français",
        "document": "document",
        "demo": "démonstration",
        "layout": "mise en page",
        "translation": "traduction",
        "This": "Ceci",
        "is": "est",
        "a": "une",
        "simple": "simple",
        "PDF": "PDF",
        "with": "avec",
        "several": "plusieurs",
        "lines": "lignes",
        "to": "pour",
        "test": "tester",
        "the": "le",
        "software": "logiciel",
    }

    def translate(self, text: str, source: str = "EN", target: str = "FR") -> str:
        """Return a deterministic pseudo-translation for local trials."""
        translated = text
        for english, french in self.replacements.items():
            translated = re.sub(rf"\b{re.escape(english)}\b", french, translated)
        return "[DEMO SANS DEEPL] " + translated


def format_ocr_lines(lines: list[OCRLine], page_width: int) -> str:
    """Format OCR lines with indentation and blank lines inferred from Tesseract boxes."""
    if not lines:
        return ""

    formatted_lines: list[str] = []
    previous_bottom: int | None = None
    average_height = max(1, sum(line.height for line in lines) // len(lines))

    for line in sorted(lines, key=lambda item: (item.top, item.left)):
        if previous_bottom is not None and line.top - previous_bottom > average_height:
            formatted_lines.append("")

        indent = int((line.left / max(page_width, 1)) * 80)
        formatted_lines.append(" " * indent + line.text)
        previous_bottom = line.top + line.height

    return "\n".join(formatted_lines)


def ocr_page_with_tesseract(page, lang: str = "eng", dpi: int = 200) -> str:
    """Run Tesseract OCR on one PyMuPDF page and keep line-level layout hints."""
    from PIL import Image
    import pytesseract

    pixmap = page.get_pixmap(dpi=dpi)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    data = pytesseract.image_to_data(
        image,
        lang=lang,
        output_type=pytesseract.Output.DICT,
        config="--psm 6",
    )

    grouped_words: dict[tuple[int, int, int], list[tuple[str, int, int, int, int]]] = {}
    for index, raw_text in enumerate(data.get("text", [])):
        word = str(raw_text).strip()
        if not word:
            continue

        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        grouped_words.setdefault(key, []).append(
            (
                word,
                int(data["left"][index]),
                int(data["top"][index]),
                int(data["width"][index]),
                int(data["height"][index]),
            )
        )

    lines: list[OCRLine] = []
    for words in grouped_words.values():
        left = min(word[1] for word in words)
        top = min(word[2] for word in words)
        right = max(word[1] + word[3] for word in words)
        bottom = max(word[2] + word[4] for word in words)
        lines.append(
            OCRLine(
                text=" ".join(word[0] for word in words),
                left=left,
                top=top,
                width=right - left,
                height=bottom - top,
            )
        )

    page_width = getattr(
        pixmap, "width", max((line.left + line.width for line in lines), default=1)
    )
    return format_ocr_lines(lines, page_width=page_width)


def extract_pdf_text(
    pdf_path: Path,
    ocr_mode: str = "auto",
    ocr_lang: str = "eng",
    ocr_dpi: int = 200,
) -> str:
    """Extract text with PyMuPDF and Tesseract OCR layout fallback for scanned pages."""
    import fitz

    if ocr_mode not in {"auto", "always", "never"}:
        raise ValueError("ocr_mode doit être 'auto', 'always' ou 'never'.")

    pages: list[str] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            text = "" if ocr_mode == "always" else (page.get_text("text") or "")
            if ocr_mode != "never" and not text.strip():
                text = ocr_page_with_tesseract(page, lang=ocr_lang, dpi=ocr_dpi)
            pages.append(f"\n\n--- Page {index} ---\n\n{text.strip()}")
    return "\n".join(pages).strip()


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> List[str]:
    """Split text into API-friendly chunks without cutting words when possible."""
    if max_chars < 200:
        raise ValueError("max_chars doit être au moins 200.")

    paragraphs = re.split(r"(\n\s*\n)", text)
    chunks: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
            current = ""

    for paragraph in paragraphs:
        if not paragraph.strip():
            if current and len(current) + len(paragraph) <= max_chars:
                current += paragraph
            continue

        if len(paragraph) > max_chars:
            flush_current()
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                if len(sentence) > max_chars:
                    chunks.extend(textwrap.wrap(sentence, width=max_chars))
                elif len(current) + len(sentence) + 1 <= max_chars:
                    current = f"{current} {sentence}".strip()
                else:
                    flush_current()
                    current = sentence
            continue

        if len(current) + len(paragraph) <= max_chars:
            current += paragraph
        else:
            flush_current()
            current = paragraph

    flush_current()
    return chunks


def translate_text(
    text: str,
    client: DeepLClient,
    source: str = "EN",
    target: str = "FR",
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Translate long text by sending multiple chunks to the translation service."""
    translated_chunks = []
    chunks = chunk_text(text, max_chars=max_chars)
    for number, chunk in enumerate(chunks, start=1):
        print(f"Traduction du bloc {number}/{len(chunks)}...", file=sys.stderr)
        translated_chunks.append(client.translate(chunk, source=source, target=target))
    return "\n\n".join(translated_chunks)


def reconstruct_pdf_with_reportlab(
    text: str, output_path: Path, title: str = "PDF traduit en français"
) -> None:
    """Reconstruct translated text into a simple paginated PDF with ReportLab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    pdf.setTitle(title)
    _width, height = A4
    margin = 50
    line_height = 14
    max_width_chars = 92
    y = height - margin

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(margin, y, title)
    y -= line_height * 2
    pdf.setFont("Helvetica", 10)

    for paragraph in text.splitlines():
        lines = textwrap.wrap(paragraph, width=max_width_chars) or [""]
        for line in lines:
            if y < margin:
                pdf.showPage()
                pdf.setFont("Helvetica", 10)
                y = height - margin
            pdf.drawString(margin, y, line)
            y -= line_height
        y -= 4

    pdf.save()


# Backward-compatible alias for callers that imported the original helper name.
write_pdf = reconstruct_pdf_with_reportlab


def translate_pdf(
    input_pdf: Path,
    output_pdf: Path,
    client: DeepLClient,
    source: str = "EN",
    target: str = "FR",
    max_chars: int = DEFAULT_MAX_CHARS,
    ocr_mode: str = "auto",
    ocr_lang: str = "eng",
    ocr_dpi: int = 200,
) -> Path:
    """Extract, translate, and export a PDF."""
    if not input_pdf.exists():
        raise FileNotFoundError(f"Fichier introuvable: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        raise ValueError("Le fichier d'entrée doit être un PDF.")

    print("Extraction du texte du PDF...", file=sys.stderr)
    original_text = extract_pdf_text(
        input_pdf, ocr_mode=ocr_mode, ocr_lang=ocr_lang, ocr_dpi=ocr_dpi
    )
    if not original_text.strip():
        raise RuntimeError(
            "Aucun texte détecté après extraction PyMuPDF et OCR Tesseract."
        )

    translated_text = translate_text(
        original_text,
        client=client,
        source=source,
        target=target,
        max_chars=max_chars,
    )
    print("Création du PDF traduit...", file=sys.stderr)
    reconstruct_pdf_with_reportlab(translated_text, output_pdf)
    return output_pdf


def create_demo_english_pdf(output_path: Path) -> Path:
    """Create a tiny English PDF that can be used to try the full workflow."""
    demo_text = """English demo document

This is a simple PDF with several lines to test the software.
The layout includes indentation and spacing.

    This indented line helps test layout handling.
"""
    reconstruct_pdf_with_reportlab(demo_text, output_path, title="English demo PDF")
    return output_path


def run_demo(demo_dir: Path) -> tuple[Path, Path]:
    """Create and translate a demo PDF locally without a DeepL API key."""
    demo_dir.mkdir(parents=True, exist_ok=True)
    input_pdf = demo_dir / "demo_anglais.pdf"
    output_pdf = demo_dir / "demo_francais.pdf"
    create_demo_english_pdf(input_pdf)
    translate_pdf(
        input_pdf,
        output_pdf,
        client=DemoTranslationClient(),
        ocr_mode="never",
    )
    return input_pdf, output_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Traduit un PDF anglais en PDF français avec DeepL API."
    )
    parser.add_argument("input", nargs="?", help="Chemin du PDF anglais à traduire")
    parser.add_argument("output", nargs="?", help="Chemin du PDF français à créer")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Crée et traduit un PDF de démonstration sans clé DeepL",
    )
    parser.add_argument(
        "--demo-dir",
        default="demo_output",
        help="Dossier de sortie du mode démonstration",
    )
    parser.add_argument("--endpoint", default=os.getenv("DEEPL_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument(
        "--auth-key",
        "--api-key",
        dest="auth_key",
        default=os.getenv("DEEPL_API_KEY"),
        help="Clé API DeepL",
    )
    parser.add_argument("--source", default="EN", help="Langue source DeepL (défaut: EN)")
    parser.add_argument("--target", default="FR", help="Langue cible DeepL (défaut: FR)")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument(
        "--ocr-mode",
        choices=("auto", "always", "never"),
        default="auto",
        help="Utilisation de Tesseract OCR pour la mise en page (défaut: auto)",
    )
    parser.add_argument("--ocr-lang", default="eng", help="Langue Tesseract OCR (défaut: eng)")
    parser.add_argument("--ocr-dpi", type=int, default=200, help="Résolution OCR en DPI")
    parser.add_argument("--gui", action="store_true", help="Ouvre une interface graphique simple")
    return parser


def run_gui(default_endpoint: str = DEFAULT_ENDPOINT) -> None:
    """Open a Tkinter user interface for non-technical users."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Traducteur PDF anglais → français")
    root.geometry("760x430")
    root.columnconfigure(1, weight=1)

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    endpoint_var = tk.StringVar(value=default_endpoint)
    auth_key_var = tk.StringVar(value=os.getenv("DEEPL_API_KEY", ""))
    source_var = tk.StringVar(value="EN")
    target_var = tk.StringVar(value="FR")
    ocr_mode_var = tk.StringVar(value="auto")
    ocr_lang_var = tk.StringVar(value="eng")
    ocr_dpi_var = tk.StringVar(value="200")
    status_var = tk.StringVar(value="Choisissez un PDF anglais à traduire.")

    def choose_input() -> None:
        filename = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if filename:
            input_var.set(filename)
            suggested = Path(filename).with_name(Path(filename).stem + "_fr.pdf")
            output_var.set(str(suggested))

    def choose_output() -> None:
        filename = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]
        )
        if filename:
            output_var.set(filename)

    def start_translation() -> None:
        translate_button.state(["disabled"])
        try:
            status_var.set("Traduction en cours...")
            root.update_idletasks()
            client = DeepLClient(
                endpoint=endpoint_var.get().strip() or DEFAULT_ENDPOINT,
                auth_key=auth_key_var.get().strip() or None,
            )
            result = translate_pdf(
                Path(input_var.get()),
                Path(output_var.get()),
                client,
                source=source_var.get().strip() or "EN",
                target=target_var.get().strip() or "FR",
                ocr_mode=ocr_mode_var.get(),
                ocr_lang=ocr_lang_var.get().strip() or "eng",
                ocr_dpi=int(ocr_dpi_var.get().strip() or "200"),
            )
        except Exception as exc:  # GUI boundary: show any actionable error to the user.
            status_var.set("Erreur")
            messagebox.showerror("Traduction impossible", str(exc))
        else:
            status_var.set(f"Terminé: {result}")
            messagebox.showinfo("Succès", f"PDF traduit créé:\n{result}")
        finally:
            translate_button.state(["!disabled"])

    ttk.Label(root, text="PDF anglais").grid(row=0, column=0, sticky="w", padx=12, pady=8)
    ttk.Entry(root, textvariable=input_var, width=72).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(root, text="Parcourir", command=choose_input).grid(row=0, column=2, padx=6)

    ttk.Label(root, text="PDF français").grid(row=1, column=0, sticky="w", padx=12, pady=8)
    ttk.Entry(root, textvariable=output_var, width=72).grid(row=1, column=1, sticky="ew", padx=6)
    ttk.Button(root, text="Enregistrer", command=choose_output).grid(row=1, column=2, padx=6)

    ttk.Label(root, text="Serveur DeepL").grid(row=2, column=0, sticky="w", padx=12, pady=8)
    ttk.Entry(root, textvariable=endpoint_var, width=72).grid(row=2, column=1, sticky="ew", padx=6)

    ttk.Label(root, text="Clé API DeepL").grid(row=3, column=0, sticky="w", padx=12, pady=8)
    ttk.Entry(root, textvariable=auth_key_var, width=72, show="*").grid(
        row=3, column=1, sticky="ew", padx=6
    )

    language_frame = ttk.LabelFrame(root, text="Langues DeepL")
    language_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
    ttk.Label(language_frame, text="Source").grid(row=0, column=0, sticky="w", padx=8, pady=8)
    ttk.Entry(language_frame, textvariable=source_var, width=12).grid(row=0, column=1, padx=8)
    ttk.Label(language_frame, text="Cible").grid(row=0, column=2, sticky="w", padx=8, pady=8)
    ttk.Entry(language_frame, textvariable=target_var, width=12).grid(row=0, column=3, padx=8)

    ocr_frame = ttk.LabelFrame(root, text="OCR Tesseract et mise en page")
    ocr_frame.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=8)
    ttk.Label(ocr_frame, text="Mode OCR").grid(row=0, column=0, sticky="w", padx=8, pady=8)
    ttk.Combobox(
        ocr_frame,
        textvariable=ocr_mode_var,
        values=("auto", "always", "never"),
        state="readonly",
        width=10,
    ).grid(row=0, column=1, padx=8)
    ttk.Label(ocr_frame, text="Langue").grid(row=0, column=2, sticky="w", padx=8, pady=8)
    ttk.Entry(ocr_frame, textvariable=ocr_lang_var, width=12).grid(row=0, column=3, padx=8)
    ttk.Label(ocr_frame, text="DPI").grid(row=0, column=4, sticky="w", padx=8, pady=8)
    ttk.Entry(ocr_frame, textvariable=ocr_dpi_var, width=8).grid(row=0, column=5, padx=8)

    translate_button = ttk.Button(root, text="Traduire avec Tkinter", command=start_translation)
    translate_button.grid(row=6, column=1, pady=14)
    ttk.Label(root, textvariable=status_var).grid(row=7, column=0, columnspan=3, padx=12)

    root.mainloop()


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        run_gui(args.endpoint)
        return 0

    if args.demo:
        try:
            input_pdf, output_pdf = run_demo(Path(args.demo_dir))
        except Exception as exc:
            print(f"Erreur du mode démonstration: {exc}", file=sys.stderr)
            return 1
        print(f"PDF de démonstration créé: {input_pdf}")
        print(f"PDF traduit de démonstration créé: {output_pdf}")
        print("Mode démonstration: aucune clé DeepL ni connexion réseau utilisée.")
        return 0

    if not args.input or not args.output:
        parser.error("input et output sont requis, sauf avec --gui")

    client = DeepLClient(endpoint=args.endpoint, auth_key=args.auth_key)
    try:
        result = translate_pdf(
            Path(args.input),
            Path(args.output),
            client=client,
            source=args.source,
            target=args.target,
            max_chars=args.max_chars,
            ocr_mode=args.ocr_mode,
            ocr_lang=args.ocr_lang,
            ocr_dpi=args.ocr_dpi,
        )
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 1

    print(f"PDF traduit créé: {result}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
