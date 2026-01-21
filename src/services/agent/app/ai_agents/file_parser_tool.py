"""
file_parser_tool.py
--------------------
Parses text from common file types (txt, pdf, csv). Implements Tool.run.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple, Any
import io
import os
import csv
import requests

try:
    from pypdf import PdfReader  # type: ignore
    _PDF_AVAILABLE = True
except Exception:
    PdfReader = None  # type: ignore
    _PDF_AVAILABLE = False


class FileParserTool:
    name = "parse_file"

    def __init__(self, max_download_bytes: int = 5 * 1024 * 1024):
        self.max_download_bytes = max_download_bytes

    def run(self, payload: Dict[str, Any]) -> str:
        file_url = payload.get("file_url")
        file_content = payload.get("file_content")
        if isinstance(file_content, str):
            file_content_bytes = file_content.encode("utf-8", errors="replace")
        else:
            file_content_bytes = file_content
        file_type = payload.get("file_type")
        filename = payload.get("filename")

        if file_url is None and file_content_bytes is None:
            raise ValueError("Either file_url or file_content must be provided")

        content, _ = self._load_content(file_url, file_content_bytes)
        kind = self._infer_type(file_type, filename, file_url, content)
        text = self._extract_text(content, kind)
        return text

    def _load_content(self, file_url: Optional[str], file_content: Optional[bytes]) -> Tuple[bytes, str]:
        if file_content is not None:
            return file_content, ""
        assert file_url is not None
        with requests.get(file_url, stream=True, timeout=15) as resp:
            resp.raise_for_status()
            content = b""
            for chunk in resp.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > self.max_download_bytes:
                    raise ValueError("Downloaded file exceeds max allowed size")
            content_type = resp.headers.get("Content-Type", "")
        return content, content_type

    def _infer_type(
        self,
        file_type: Optional[str],
        filename: Optional[str],
        file_url: Optional[str],
        content: bytes,
    ) -> str:
        if file_type:
            return file_type.lower()
        name = filename or (file_url or "")
        _, ext = os.path.splitext(name.lower())
        if ext in {".txt"}:
            return "txt"
        if ext in {".pdf"}:
            return "pdf"
        if ext in {".csv"}:
            return "csv"
        if content[:4] == b"%PDF":
            return "pdf"
        try:
            content.decode("utf-8")
            return "txt"
        except Exception:
            return "bin"

    def _extract_text(self, content: bytes, kind: str) -> str:
        if kind == "txt":
            return content.decode("utf-8", errors="replace")
        if kind == "csv":
            return self._extract_csv(content)
        if kind == "pdf":
            if not _PDF_AVAILABLE:
                raise RuntimeError("PDF parsing requested but pypdf is not installed")
            return self._extract_pdf(content)
        return ""

    def _extract_csv(self, content: bytes) -> str:
        text_stream = io.StringIO(content.decode("utf-8", errors="replace"))
        reader = csv.reader(text_stream)
        rows = [", ".join(row) for row in reader]
        return "\n".join(rows)

    def _extract_pdf(self, content: bytes) -> str:
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            parts.append(page_text)
        return "\n".join(parts)


