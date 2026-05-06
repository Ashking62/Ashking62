import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from pdf_translator_fr import (
    DeepLClient,
    DemoTranslationClient,
    TranslationError,
    build_parser,
    chunk_text,
    extract_pdf_text,
    ocr_page_with_tesseract,
    reconstruct_pdf_with_reportlab,
    translate_text,
)


class FakeClient(DeepLClient):
    def __init__(self):
        self.calls = []

    def translate(self, text, source="EN", target="FR"):
        self.calls.append((text, source, target))
        return f"FR:{text}"


class FakePage:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def get_text(self, mode):
        self.calls.append(mode)
        return self.text


class FakeDocument:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(self.pages)


class FakeResponse:
    status_code = 200
    text = "OK"

    def json(self):
        return {"translations": [{"detected_source_language": "EN", "text": "Bonjour"}]}


class FakeRequests:
    class RequestException(Exception):
        pass

    def __init__(self):
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return FakeResponse()


class FakePixmap:
    width = 1000

    def tobytes(self, image_format):
        self.image_format = image_format
        return b"png-bytes"


class FakeOCRPage:
    def __init__(self):
        self.pixmap = FakePixmap()
        self.requested_dpi = None

    def get_pixmap(self, dpi):
        self.requested_dpi = dpi
        return self.pixmap


class FakeTesseract:
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self):
        self.calls = []

    def image_to_data(self, image, lang, output_type, config):
        self.calls.append(
            {
                "image": image,
                "lang": lang,
                "output_type": output_type,
                "config": config,
            }
        )
        return {
            "text": ["Hello", "world", "", "Indented"],
            "block_num": [1, 1, 1, 2],
            "par_num": [1, 1, 1, 1],
            "line_num": [1, 1, 1, 1],
            "left": [10, 70, 0, 250],
            "top": [20, 20, 20, 80],
            "width": [50, 60, 0, 100],
            "height": [12, 12, 0, 14],
        }


class FakeCanvas:
    instances = []

    def __init__(self, path, pagesize):
        self.path = path
        self.pagesize = pagesize
        self.operations = []
        FakeCanvas.instances.append(self)

    def setTitle(self, title):
        self.operations.append(("setTitle", title))

    def setFont(self, family, size):
        self.operations.append(("setFont", family, size))

    def drawString(self, x, y, text):
        self.operations.append(("drawString", x, y, text))

    def showPage(self):
        self.operations.append(("showPage",))

    def save(self):
        self.operations.append(("save",))


class DemoModeTests(unittest.TestCase):
    def test_demo_translation_client_does_not_require_deepl_key(self):
        client = DemoTranslationClient()

        translated = client.translate("English demo document")

        self.assertIn("[DEMO SANS DEEPL]", translated)
        self.assertIn("anglais", translated)
        self.assertIn("démonstration", translated)

    def test_parser_accepts_demo_mode_without_input_output(self):
        args = build_parser().parse_args(["--demo", "--demo-dir", "essai"])

        self.assertTrue(args.demo)
        self.assertEqual(args.demo_dir, "essai")
        self.assertIsNone(args.input)
        self.assertIsNone(args.output)


class DeepLClientTests(unittest.TestCase):
    def test_translate_calls_deepl_api(self):
        fake_requests = FakeRequests()
        client = DeepLClient(endpoint="https://api-free.deepl.com", auth_key="secret")

        with patch.dict(sys.modules, {"requests": fake_requests}):
            translated = client.translate("Hello", source="EN", target="FR")

        self.assertEqual(translated, "Bonjour")
        self.assertEqual(len(fake_requests.calls), 1)
        call = fake_requests.calls[0]
        self.assertEqual(call["url"], "https://api-free.deepl.com/v2/translate")
        self.assertEqual(
            call["json"], {"text": ["Hello"], "target_lang": "FR", "source_lang": "EN"}
        )
        self.assertEqual(call["headers"]["Authorization"], "DeepL-Auth-Key secret")

    def test_translate_requires_auth_key(self):
        client = DeepLClient(auth_key=None)

        with self.assertRaises(TranslationError):
            client.translate("Hello")


class ExtractPdfTextTests(unittest.TestCase):
    def test_extract_pdf_text_uses_pymupdf_text_mode(self):
        first_page = FakePage("Hello world")
        second_page = FakePage("Second page")
        fake_document = FakeDocument([first_page, second_page])
        fake_fitz = types.SimpleNamespace(open=lambda path: fake_document)

        with patch.dict(sys.modules, {"fitz": fake_fitz}):
            text = extract_pdf_text("sample.pdf")

        self.assertIn("--- Page 1 ---", text)
        self.assertIn("Hello world", text)
        self.assertIn("--- Page 2 ---", text)
        self.assertIn("Second page", text)
        self.assertEqual(first_page.calls, ["text"])
        self.assertEqual(second_page.calls, ["text"])


class ChunkTextTests(unittest.TestCase):
    def test_chunk_text_keeps_chunks_under_limit(self):
        text = "One sentence. " * 120
        chunks = chunk_text(text, max_chars=250)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 250 for chunk in chunks))

    def test_chunk_text_rejects_tiny_limit(self):
        with self.assertRaises(ValueError):
            chunk_text("hello", max_chars=100)


class TesseractOCRTests(unittest.TestCase):
    def test_ocr_page_with_tesseract_keeps_line_layout_hints(self):
        fake_page = FakeOCRPage()
        fake_tesseract = FakeTesseract()
        fake_image_module = types.SimpleNamespace(open=lambda stream: "image-from-png")
        fake_pil = types.SimpleNamespace(Image=fake_image_module)

        with patch.dict(
            sys.modules,
            {
                "PIL": fake_pil,
                "PIL.Image": fake_image_module,
                "pytesseract": fake_tesseract,
            },
        ):
            text = ocr_page_with_tesseract(fake_page, lang="eng", dpi=300)

        self.assertEqual(fake_page.requested_dpi, 300)
        self.assertEqual(fake_page.pixmap.image_format, "png")
        self.assertEqual(fake_tesseract.calls[0]["lang"], "eng")
        self.assertEqual(fake_tesseract.calls[0]["output_type"], "dict")
        self.assertIn("Hello world", text)
        self.assertIn("                    Indented", text)

class ReconstructPdfWithReportLabTests(unittest.TestCase):
    def test_reconstruct_pdf_uses_reportlab_canvas(self):
        FakeCanvas.instances = []
        fake_pagesizes = types.SimpleNamespace(A4=(595, 842))
        fake_canvas_module = types.SimpleNamespace(Canvas=FakeCanvas)

        with patch.dict(
            sys.modules,
            {
                "reportlab": types.SimpleNamespace(),
                "reportlab.lib": types.SimpleNamespace(),
                "reportlab.lib.pagesizes": fake_pagesizes,
                "reportlab.pdfgen": types.SimpleNamespace(canvas=fake_canvas_module),
                "reportlab.pdfgen.canvas": fake_canvas_module,
            },
        ):
            reconstruct_pdf_with_reportlab("Bonjour\nle monde", Path("translated.pdf"))

        self.assertEqual(len(FakeCanvas.instances), 1)
        canvas = FakeCanvas.instances[0]
        self.assertEqual(canvas.path, "translated.pdf")
        self.assertEqual(canvas.pagesize, (595, 842))
        self.assertIn(("setTitle", "PDF traduit en français"), canvas.operations)
        self.assertIn(
            ("drawString", 50, 792, "PDF traduit en français"), canvas.operations
        )
        self.assertIn(("save",), canvas.operations)


class TranslateTextTests(unittest.TestCase):
    def test_translate_text_uses_requested_languages(self):
        client = FakeClient()
        result = translate_text("Hello world.", client, source="EN", target="FR")
        self.assertEqual(result, "FR:Hello world.")
        self.assertEqual(client.calls, [("Hello world.", "EN", "FR")])


if __name__ == "__main__":
    unittest.main()
