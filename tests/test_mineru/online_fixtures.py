"""Synthetic fixtures for the MinerU online PDF translation path.

Everything here is generated locally: synthetic source PDFs, a synthetic
provider result archive that matches an admitted PDF's fingerprint and page
count, and an in-process fake of the external HTTP contract.

The fake HTTP layer is the only external thing a test substitutes: it replaces
``requests.Session.request`` so the real ``MineruClient`` (headers, deadlines,
validation) runs unchanged.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import pymupdf
from PIL import Image

API_BASE = "https://mineru.net/api/v4"
UPLOAD_URL = (
    "https://mineru-upload.oss-cn-hangzhou.aliyuncs.com/upload/doc-1"
    "?Expires=1&Signature=upload-signature"
)
RESULT_URL = (
    "https://mineru-result.oss-cn-hangzhou.aliyuncs.com/result/doc-1.zip"
    "?Expires=1&Signature=result-signature"
)
BATCH_ID = "batch-abc123"
FILE_NAME = "source.pdf"

PAGE_WIDTH = 600.0
PAGE_HEIGHT = 800.0

# V2 boxes are normalised to a 1000 x 1000 square (see src/core/mineru/cache.py)
NORMALISED = 1000.0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


# ---------------------------------------------------------------------------
# Source PDFs
# ---------------------------------------------------------------------------


def build_source_pdf(path: Path, pages: int = 3, *, text_layer: bool = True) -> Path:
    """Write a small synthetic source PDF with (or without) a text layer."""
    document = pymupdf.open()
    try:
        for number in range(1, pages + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if text_layer:
                page.insert_text((60, 90), f"Chapter {number}", fontsize=20)
                page.insert_text(
                    (60, 140),
                    f"Body paragraph number {number}.",
                    fontsize=11,
                )
            else:
                # A scanned page: vector content only, no extractable text.
                page.draw_rect(pymupdf.Rect(60, 90, 540, 700), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(path))
    finally:
        document.close()
    return path


def build_encrypted_pdf(path: Path) -> Path:
    document = pymupdf.open()
    try:
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.insert_text((60, 90), "Secret", fontsize=20)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(
            str(path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    finally:
        document.close()
    return path


def build_corrupt_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\nthis is not a pdf body\n")
    return path


# ---------------------------------------------------------------------------
# Result archive (what the provider returns after recognition)
# ---------------------------------------------------------------------------


def _png_bytes(width: int = 60, height: int = 40) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 120, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _points(bbox: List[float]) -> List[float]:
    return [
        bbox[0] * PAGE_WIDTH / NORMALISED,
        bbox[1] * PAGE_HEIGHT / NORMALISED,
        bbox[2] * PAGE_WIDTH / NORMALISED,
        bbox[3] * PAGE_HEIGHT / NORMALISED,
    ]


def title_block(text: str, bbox: List[float], level: int = 1) -> Dict[str, Any]:
    return {"type": "title", "level": level, "text": text, "bbox": bbox}


def paragraph_block(text: str, bbox: List[float]) -> Dict[str, Any]:
    return {"type": "paragraph", "text": text, "bbox": bbox}


def image_block(path: str, bbox: List[float], *, caption: str = "",
                footnote: str = "", content: str = "") -> Dict[str, Any]:
    return {
        "type": "image",
        "path": path,
        "bbox": bbox,
        "caption": [{"type": "text", "content": caption}] if caption else [],
        "footnote": [{"type": "text", "content": footnote}] if footnote else [],
        "text": content,
    }


def footnote_block(text: str, bbox: List[float]) -> Dict[str, Any]:
    return {"type": "page_footnote", "text": text, "bbox": bbox}


def header_block(text: str, bbox: List[float]) -> Dict[str, Any]:
    return {"type": "page_header", "text": text, "bbox": bbox}


def default_result_pages(page_count: int) -> List[List[Dict[str, Any]]]:
    """A deterministic recognised page layout for a ``page_count``-page PDF."""
    pages: List[List[Dict[str, Any]]] = []
    for index in range(page_count):
        blocks: List[Dict[str, Any]] = []
        if index == 0:
            blocks.append(title_block("SAMPLE BOOK", [60, 80, 940, 140]))
            blocks.append(paragraph_block("Ada Lovelace", [60, 160, 400, 190]))
        blocks.append(paragraph_block(
            f"Body paragraph number {index + 1}.", [60, 220, 540, 300]))
        if index == 1 or (page_count == 1 and index == 0):
            blocks.append(image_block(
                "images/fig1.png", [60, 330, 940, 700],
                caption="Figure 1: a caption", footnote="Figure credit."))
        if index == page_count - 1:
            blocks.append(footnote_block(
                f"A substantive footnote for page {index + 1}.",
                [60, 720, 540, 760]))
        pages.append(blocks)
    return pages


def _v2_block(spec: Dict[str, Any]) -> Dict[str, Any]:
    kind = spec["type"]
    bbox = spec["bbox"]
    if kind == "title":
        return {
            "type": "title",
            "bbox": bbox,
            "content": {
                "title_content": [{"type": "text", "content": spec["text"]}],
                "level": spec.get("level", 1),
            },
        }
    if kind == "paragraph":
        return {
            "type": "paragraph",
            "bbox": bbox,
            "content": {"paragraph_content": [{"type": "text", "content": spec["text"]}]},
        }
    if kind == "image":
        return {
            "type": "image",
            "bbox": bbox,
            "content": {
                "image_source": {"path": spec["path"]},
                "content": spec.get("text", ""),
                "image_caption": spec.get("caption", []),
                "image_footnote": spec.get("footnote", []),
            },
        }
    key = {
        "page_footnote": "page_footnote_content",
        "page_header": "page_header_content",
        "page_number": "page_number_content",
    }.get(kind)
    if key is None:
        # An unsupported recognised block type: the loader must reject it
        # explicitly rather than omit it silently.
        return {"type": kind, "bbox": bbox, "content": {}}
    return {"type": kind, "bbox": bbox, "content": {key: [{"type": "text", "content": spec["text"]}]}}


def _layout_block(spec: Dict[str, Any], index: int) -> Dict[str, Any]:
    points = _points(spec["bbox"])
    if spec["type"] == "image":
        return {"type": "image", "bbox": points, "index": index, "lines": []}
    block: Dict[str, Any] = {
        "type": "title" if spec["type"] == "title" else "text",
        "bbox": points,
        "index": index,
        "lines": [{
            "bbox": points,
            "spans": [{"bbox": points, "type": "text", "content": spec["text"]}],
        }],
    }
    if spec["type"] == "title":
        block["level"] = spec.get("level", 1)
    return block


def result_zip_bytes(
    *,
    page_count: int,
    pages: Optional[List[List[Dict[str, Any]]]] = None,
    extra_members: Optional[Dict[str, bytes]] = None,
    layout_page_count: Optional[int] = None,
    symlink_member: Optional[str] = None,
) -> bytes:
    """Render the provider result archive as bytes.

    ``layout_page_count`` lets a test claim a different number of recognised
    pages than the admitted source, i.e. an incomplete result.
    """
    pages = pages if pages is not None else default_result_pages(page_count)
    recognised = page_count if layout_page_count is None else layout_page_count

    layout_pages = []
    for index in range(recognised):
        blocks = pages[index] if index < len(pages) else []
        layout_pages.append({
            "page_idx": index,
            "page_size": [PAGE_WIDTH, PAGE_HEIGHT],
            "preproc_blocks": [
                _layout_block(spec, position) for position, spec in enumerate(blocks)
                if spec["type"] in ("title", "paragraph", "image")
            ],
            "discarded_blocks": [
                _layout_block(spec, position) for position, spec in enumerate(blocks)
                if spec["type"] not in ("title", "paragraph", "image")
            ],
        })
    layout = {
        "pdf_info": layout_pages,
        "_backend": "hybrid",
        "_version_name": "2.5.4",
        "_ocr_enable": True,
    }
    v2 = [[_v2_block(spec) for spec in page] for page in pages[:recognised]]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("layout.json", json.dumps(layout, ensure_ascii=False, indent=2))
        archive.writestr(
            "sample_content_list_v2.json",
            json.dumps(v2, ensure_ascii=False, indent=2),
        )
        archive.writestr("images/fig1.png", _png_bytes())
        for name, data in (extra_members or {}).items():
            archive.writestr(name, data)
        if symlink_member:
            info = zipfile.ZipInfo(symlink_member)
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "../../outside")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Fake external HTTP
# ---------------------------------------------------------------------------


def response(url: str, body: bytes = b"", status: int = 200,
             headers: Optional[Dict[str, str]] = None):
    """Build a real ``requests.Response`` the client code can consume."""
    import requests

    result = requests.Response()
    result.status_code = status
    result.url = url
    result.headers = dict(headers or {})
    result._content = body
    result._content_consumed = True
    result.encoding = "utf-8"
    return result


class FakeMineruHttp:
    """Minimal scripted stand-in for the external MinerU HTTP contract.

    Every request is recorded so a test can assert what the application sent:
    counts, headers (credential separation) and bodies.
    """

    def __init__(self, zip_bytes: Optional[bytes] = None):
        self.zip_bytes = zip_bytes
        self.requests: List[Dict[str, Any]] = []
        # Successive poll responses; the last one repeats.
        self.poll_states: List[str] = ["done"]
        self.uploaded_name: Optional[str] = None
        # Overrides, each either a response factory or a raw response tuple.
        self.submit_override: Optional[Callable[[], Any]] = None
        self.status_override: Optional[Callable[[int], Any]] = None
        self.upload_override: Optional[Callable[[], Any]] = None
        self.download_override: Optional[Callable[[], Any]] = None
        self.poll_count = 0

    # -- test helpers --------------------------------------------------
    def calls(self, predicate: Optional[Callable[[Dict[str, Any]], bool]] = None):
        return [item for item in self.requests if predicate is None or predicate(item)]

    def api_calls(self):
        return self.calls(lambda item: item["url"].startswith(API_BASE + "/"))

    def storage_calls(self):
        return self.calls(lambda item: not item["url"].startswith(API_BASE + "/"))

    def submitted_files(self) -> List[Dict[str, Any]]:
        found = []
        for item in self.api_calls():
            if item["method"] == "POST" and item["url"].endswith("/file-urls/batch"):
                found.append(item["json"])
        return found

    # -- dispatch ------------------------------------------------------
    def dispatch(self, method: str, url: str, **kwargs):
        payload = kwargs.get("json")
        record = {
            "method": method.upper(),
            "url": url,
            "headers": dict(kwargs.get("headers") or {}),
            "json": payload,
            "stream": bool(kwargs.get("stream")),
            "allow_redirects": kwargs.get("allow_redirects"),
        }
        self.requests.append(record)

        if method.upper() == "POST" and url == f"{API_BASE}/file-urls/batch":
            if self.submit_override is not None:
                return self._apply_override(self.submit_override)
            files = (payload or {}).get("files") or []
            self.uploaded_name = files[0].get("name") if files else None
            return response(url, json.dumps({
                "code": 0,
                "data": {"batch_id": BATCH_ID, "file_urls": [UPLOAD_URL]},
            }).encode("utf-8"))

        if method.upper() == "PUT" and url == UPLOAD_URL:
            if self.upload_override is not None:
                return self._apply_override(self.upload_override)
            return response(url, status=200)

        if method.upper() == "GET" and url.startswith(f"{API_BASE}/extract-results/batch/"):
            index = self.poll_count
            self.poll_count += 1
            if self.status_override is not None:
                return self._apply_override(lambda: self.status_override(index))
            state = self.poll_states[min(index, len(self.poll_states) - 1)]
            row: Dict[str, Any] = {
                "file_name": self.uploaded_name or FILE_NAME,
                "state": state,
            }
            if state == "done":
                row["full_zip_url"] = RESULT_URL
            if state == "failed":
                row["err_msg"] = "recognition failed remotely"
            return response(url, json.dumps({
                "code": 0,
                "data": {"extract_result": [row]},
            }).encode("utf-8"))

        if method.upper() == "GET" and url == RESULT_URL:
            if self.download_override is not None:
                return self._apply_override(self.download_override)
            return response(url, self.zip_bytes or b"")

        return response(url, b'{"code":404}', status=404)

    @staticmethod
    def _apply_override(override):
        value = override() if callable(override) else override
        return value


def install_fake_http(monkeypatch, fake: FakeMineruHttp) -> FakeMineruHttp:
    import requests

    def _request(self, method, url, **kwargs):
        return fake.dispatch(method, url, **kwargs)

    monkeypatch.setattr(requests.Session, "request", _request)
    return fake


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class FakeLlmClient:
    """Replace only the external LLM: translate via the real prompt contract."""

    def __init__(self, prefix: str = "FR: "):
        from src.config import TRANSLATE_TAG_IN, TRANSLATE_TAG_OUT
        from src.core.llm.utils.extraction import TranslationExtractor

        self.prefix = prefix
        self.calls = 0
        self.system_prompts: List[str] = []
        self._extractor = TranslationExtractor(TRANSLATE_TAG_IN, TRANSLATE_TAG_OUT)

    def extract_translation(self, response: str):
        """Use the production tag extractor, like every real provider."""
        return self._extractor.extract(response)

    async def generate(self, prompt: str, timeout: int = 300,
                       system_prompt: Optional[str] = None):
        from src.core.llm.base import LLMResponse

        self.calls += 1
        self.system_prompts.append(system_prompt or "")
        content = between_tag(prompt, "<SOURCE_TEXT>", "</SOURCE_TEXT>")
        paragraphs = [part for part in content.split("\n\n")]
        translated = "\n\n".join(f"{self.prefix}{part}" for part in paragraphs)
        return LLMResponse(content=f"<TRANSLATION>\n{translated}\n</TRANSLATION>")

    async def close(self):
        return None


def between_tag(text: str, opening: str, closing: str) -> str:
    start = text.find(opening)
    end = text.find(closing)
    if start < 0 or end < 0 or end <= start:
        return text
    return text[start + len(opening):end].strip()


class FakeClock:
    """Deterministic monotonic clock: ``sleep`` advances time instead of waiting."""

    def __init__(self, start: float = 1_000.0):
        self.now = float(start)
        self.sleeps: List[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += max(0.0, float(seconds))


def install_fake_llm(monkeypatch, client: Optional[FakeLlmClient] = None) -> FakeLlmClient:
    """Substitute only the external LLM, at both provider-construction seams."""
    fake = client or FakeLlmClient()
    factory = lambda *args, **kwargs: fake  # noqa: E731 - tiny test seam
    monkeypatch.setattr("src.core.llm.create_llm_provider", factory)
    # src.core.llm_client imports the factory into its own namespace; the
    # generic adapter builds its client through that binding.
    monkeypatch.setattr("src.core.llm_client.create_llm_provider", factory)
    return fake
