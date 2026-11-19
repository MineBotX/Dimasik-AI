import tempfile
import unittest
from pathlib import Path

from assistant.file_reader import MAX_FILE_BYTES, SUPPORTED_EXTENSIONS, read_document
from docx import Document
from openpyxl import Workbook
from pptx import Presentation


class FileReaderTests(unittest.TestCase):
    def test_plain_text_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.txt"
            path.write_text("Привет, Димасик!", encoding="utf-8")
            content, truncated = read_document(path)
            self.assertEqual(content, "Привет, Димасик!")
            self.assertFalse(truncated)

    def test_plain_text_cp1251(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.txt"
            path.write_bytes("Привет".encode("cp1251"))
            content, _ = read_document(path)
            self.assertEqual(content, "Привет")

    def test_unsupported_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.exe"
            path.write_bytes(b"not executable")
            with self.assertRaises(ValueError):
                read_document(path)

    def test_oversized_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.txt"
            with path.open("wb") as handle:
                handle.truncate(MAX_FILE_BYTES + 1)
            with self.assertRaises(ValueError):
                read_document(path)


    def test_docx_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.docx"
            document = Document()
            document.add_paragraph("Краткий отчёт")
            document.save(path)
            content, truncated = read_document(path)
            self.assertIn("Краткий отчёт", content)
            self.assertFalse(truncated)

    def test_xlsx_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            workbook = Workbook()
            workbook.active["A1"] = "Выручка"
            workbook.active["B1"] = 125
            workbook.save(path)
            content, _ = read_document(path)
            self.assertIn("Выручка", content)
            self.assertIn("125", content)

    def test_pptx_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slides.pptx"
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[5])
            slide.shapes.title.text = "План проекта"
            presentation.save(path)
            content, _ = read_document(path)
            self.assertIn("План проекта", content)

    def test_document_formats_are_registered(self):
        self.assertTrue({".pdf", ".docx", ".xlsx", ".pptx"}.issubset(SUPPORTED_EXTENSIONS))


if __name__ == "__main__":
    unittest.main()
