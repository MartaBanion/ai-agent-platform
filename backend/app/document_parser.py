import io
import re
import zipfile
from pathlib import PurePath

from defusedxml import ElementTree
from pypdf import PdfReader

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 120_000
MAX_CHUNKS = 400
FORMATS = {"txt", "md", "markdown", "pdf", "docx"}
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(Exception):
    pass


def validated_name(name, body):
    name = PurePath((name or "").replace("\\", "/")).name
    suffix = PurePath(name).suffix.lower().lstrip(".")
    if not name or len(name) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise DocumentError("文件名无效")
    if suffix not in FORMATS:
        raise DocumentError("支持 PDF、DOCX、TXT 和 Markdown")
    if not body or len(body) > MAX_FILE:
        raise DocumentError("文件为空或超过 8 MiB")
    if suffix == "pdf" and not body.startswith(b"%PDF-"):
        raise DocumentError("PDF 文件签名无效")
    if suffix == "docx" and not body.startswith(b"PK\x03\x04"):
        raise DocumentError("DOCX 文件签名无效")
    if suffix in {"txt", "md", "markdown"} and b"\x00" in body:
        raise DocumentError("文本文件须使用 UTF-8 编码")
    return name, suffix


def word_text(body):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        entries = archive.infolist()
        if len(entries) > 1500 or sum(entry.file_size for entry in entries) > 24 * 1024 * 1024:
            raise DocumentError("DOCX 解包超过限制")
        info = archive.getinfo("word/document.xml")
        if info.file_size > 4 * 1024 * 1024:
            raise DocumentError("DOCX 正文超过限制")
        root = ElementTree.fromstring(archive.read(info))
    return "\n".join("".join(item.text or "" for item in para.iter(WORD + "t"))
                     for para in root.iter(WORD + "p"))


def pages(kind, body):
    try:
        if kind == "pdf":
            reader = PdfReader(io.BytesIO(body), strict=True)
            if reader.is_encrypted:
                raise DocumentError("不支持加密 PDF")
            if len(reader.pages) > 80:
                raise DocumentError("PDF 超过 80 页")
            yield from ((number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1))
        elif kind == "docx":
            yield None, word_text(body)
        else:
            yield None, body.decode("utf-8-sig")
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("文件损坏、格式不兼容或不是 UTF-8 文本") from None


def passages(kind, body, size, overlap):
    result, total = [], 0
    for page, raw in pages(kind, body):
        text = re.sub(r"\s+", " ", raw).strip()
        total += len(text)
        if total > MAX_TEXT:
            raise DocumentError("提取文本超过 120,000 字符")
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                boundary = max(text.rfind(char, start + size // 2, end) for char in ("。", "！", "？", " ", "."))
                if boundary != -1:
                    end = boundary + 1
            result.append((page, text[start:end].strip()))
            if len(result) > MAX_CHUNKS:
                raise DocumentError("片段超过 400 条，请增大切分长度或拆分文档")
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    if not result:
        raise DocumentError("文档无可提取文字，扫描 PDF 需要先进行 OCR")
    return result
