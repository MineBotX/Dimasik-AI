"""Безопасное извлечение текста из пользовательских документов без исполнения их содержимого."""
from __future__ import annotations

from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 18000
SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".yaml",
    ".yml", ".html", ".css", ".js", ".xml", ".toml",
    ".pdf", ".docx", ".xlsx", ".pptx",
}


def _plain_text(path: Path) -> str:
    payload = path.read_bytes()
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return payload.decode("cp1251", errors="replace")


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            raise ValueError("PDF защищён паролем. Сними защиту или выбери другой файл.")
    pieces = []
    for index, page in enumerate(reader.pages[:300], start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            pieces.append(f"Страница {index}:\n{page_text}")
    if not pieces:
        raise ValueError("В PDF не найден текст. Возможно, это скан без текстового слоя.")
    return "\n\n".join(pieces)


def _docx_text(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    pieces = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table_index, table in enumerate(document.tables, start=1):
        pieces.append(f"Таблица {table_index}:")
        for row in table.rows[:250]:
            pieces.append(" | ".join(cell.text.replace("\n", " ").strip() for cell in row.cells))
    return "\n".join(pieces)


def _xlsx_text(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=str(path), read_only=True, data_only=True, keep_links=False)
    pieces = []
    try:
        for worksheet in workbook.worksheets[:8]:
            pieces.append(f"Лист: {worksheet.title}")
            for row in worksheet.iter_rows(min_row=1, max_row=200, max_col=30, values_only=True):
                values = [str(value)[:500] if value is not None else "" for value in row]
                while values and not values[-1]:
                    values.pop()
                if values:
                    pieces.append(" | ".join(values))
    finally:
        workbook.close()
    return "\n".join(pieces)


def _pptx_text(path: Path) -> str:
    from pptx import Presentation

    presentation = Presentation(str(path))
    pieces = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        if slide_number > 100:
            break
        pieces.append(f"Слайд {slide_number}:")
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text:
                    pieces.append(text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    pieces.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(pieces)


def read_document(path: Path | str, max_chars: int = MAX_TEXT_CHARS) -> tuple[str, bool]:
    """Возвращает извлечённый текст и признак обрезки; ничего не запускает."""
    selected = Path(path)
    suffix = selected.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Этот формат пока не поддерживается. Используй PDF, DOCX, XLSX, PPTX или текстовый файл.")
    try:
        size = selected.stat().st_size
    except OSError as exc:
        raise ValueError(f"Не удалось открыть файл: {exc}") from exc
    if size > MAX_FILE_BYTES:
        raise ValueError("Файл больше 25 МБ. Выбери документ поменьше.")
    if suffix == ".pdf":
        text = _pdf_text(selected)
    elif suffix == ".docx":
        text = _docx_text(selected)
    elif suffix == ".xlsx":
        text = _xlsx_text(selected)
    elif suffix == ".pptx":
        text = _pptx_text(selected)
    else:
        text = _plain_text(selected)
    text = str(text or "").strip()
    if not text:
        raise ValueError("В файле не найден текст для анализа.")
    limit = max(1000, min(int(max_chars), 50000))
    truncated = len(text) > limit
    if truncated:
        text = text[:limit] + "\n\n[Текст документа сокращён.]"
    return text, truncated
