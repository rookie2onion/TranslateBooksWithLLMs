"""Probe MinerU online VLM with at most five source pages; never call a translation LLM.

Credentials are loaded only from the worktree's private .env. Evidence stays in
Git-ignored data/. Reusing a run directory resumes its batch, not a new upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlsplit

import pymupdf
import requests
from dotenv import dotenv_values
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.utils.security import safe_extract_zip  # noqa: E402

API = "https://mineru.net/api/v4"
MAX_PAGES = 5
MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(source: Path, pages: list[int], run: Path) -> dict:
    metadata_path = run / "sample-info.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if source != Path(metadata["source_path"]) or pages != metadata["source_pages"]:
            raise ValueError("This run belongs to a different source or page selection.")
        if fingerprint(source) != metadata["source_sha256"]:
            raise ValueError("Source bytes changed; this run cannot be reused.")
        return metadata
    if not pages or len(pages) > MAX_PAGES or len(set(pages)) != len(pages):
        raise ValueError("Select one to five distinct source pages.")
    if (run / "sample.pdf").exists():
        raise ValueError("An incomplete sample already exists; inspect it before continuing.")
    before = fingerprint(source)
    thumbnails, page_stats = [], []
    with pymupdf.open(source) as original, pymupdf.open() as sample:
        if original.needs_pass:
            raise ValueError("The source PDF requires a password.")
        if any(page < 1 or page > len(original) for page in pages):
            raise ValueError("A selected source page is out of range.")
        for number in pages:
            sample.insert_pdf(original, from_page=number - 1, to_page=number - 1,
                              links=False, annots=False)
            page = original[number - 1]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(0.65, 0.65),
                                     colorspace=pymupdf.csRGB, alpha=False)
            thumbnails.append(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
            page_stats.append({"source_page": number, "native_text_chars": len(page.get_text().strip()),
                               "native_images": len(page.get_images())})
        sample.set_metadata({})
        sample.save(run / "sample.pdf", garbage=4, clean=True, deflate=True)
        source_count = len(original)
    if fingerprint(source) != before:
        raise ValueError("The source changed during preparation; nothing may be uploaded.")
    width = max(image.width for image in thumbnails)
    height = max(image.height for image in thumbnails) + 28
    preview = Image.new("RGB", (width * 2, height * ((len(pages) + 1) // 2)), "#eeeeee")
    draw = ImageDraw.Draw(preview)
    for index, (number, image) in enumerate(zip(pages, thumbnails)):
        x, y = index % 2 * width, index // 2 * height
        draw.text((x + 8, y + 6), f"Source PDF page {number}", fill="black")
        preview.paste(image, (x, y + 26))
    preview.save(run / "source-preview.jpg", quality=90)
    metadata = {"source_path": str(source), "source_sha256": before,
                "source_total_pages": source_count, "source_pages": pages,
                "sample_sha256": fingerprint(run / "sample.pdf"), "page_stats": page_stats,
                "translation_llm_called": False}
    save_json(metadata_path, metadata)
    return metadata


def storage_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    allowed = any(host.endswith(suffix) for suffix in (".aliyuncs.com", ".openxlab.org.cn"))
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not allowed:
        raise ValueError("The returned storage host is not an approved HTTPS storage host.")
    return value


def api_json(session: requests.Session, method: str, path: str, token: str, **kwargs) -> dict:
    response = session.request(method, API + path,
                               headers={"Authorization": "Bearer " + token},
                               timeout=(15, 60), allow_redirects=False, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"MinerU returned non-JSON data (HTTP {response.status_code}).") from None
    if response.status_code != 200 or payload.get("code") != 0:
        code = str(payload.get("code", "unknown"))
        raise RuntimeError(f"MinerU rejected the request (HTTP {response.status_code}, code {code}).")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("MinerU returned an unexpected response structure.")
    return data


def inspect_archive(path: Path, run: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 2000 or sum(item.file_size for item in members) > MAX_EXPANDED:
            raise ValueError("The result archive exceeds the probe's safety limits.")
        if any(stat.S_ISLNK(item.external_attr >> 16) for item in members):
            raise ValueError("The result archive contains a symbolic link.")
        folded = [item.filename.casefold() for item in members]
        if len(folded) != len(set(folded)):
            raise ValueError("The result archive contains colliding member names.")
        safe_extract_zip(archive, run / "result")
    result = run / "result"
    json_shapes, content_types, content_pages = {}, Counter(), set()
    for member in sorted(result.rglob("*.json")):
        if member.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("A result JSON file exceeds the probe's safety limit.")
        value = json.loads(member.read_text(encoding="utf-8"))
        shape = {"kind": type(value).__name__}
        if isinstance(value, dict):
            shape["keys"] = list(value)[:24]
            shape["version"] = value.get("_version", value.get("version"))
            if isinstance(value.get("pdf_info"), list):
                shape["page_count"] = len(value["pdf_info"])
        elif isinstance(value, list):
            shape["length"] = len(value)
        json_shapes[member.relative_to(result).as_posix()] = shape
        if member.name.endswith("content_list.json") and isinstance(value, list):
            for block in value:
                if isinstance(block, dict):
                    content_types[str(block.get("type", "unknown"))] += 1
                    index = block.get("page_idx")
                    if isinstance(index, int):
                        content_pages.add(index)
    images = [p for p in result.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    for image_path in images:
        with Image.open(image_path) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("A result image exceeds the probe's pixel limit.")
            image.verify()
    return {"zip_bytes": path.stat().st_size, "json_shapes": json_shapes,
            "content_types": dict(content_types), "content_page_indices": sorted(content_pages),
            "image_files": len(images),
            "markdown_files": [p.relative_to(result).as_posix() for p in result.rglob("*.md")]}


def recognize(run: Path, token: str, timeout: int) -> dict:
    state_path = run / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    sample = run / "sample.pdf"
    with pymupdf.open(sample) as document:
        if not 1 <= len(document) <= MAX_PAGES:
            raise ValueError("The upload must contain at most five pages.")
    if sample.stat().st_size > 200_000_000:
        raise ValueError("The sample exceeds MinerU's file size limit.")
    metadata = json.loads((run / "sample-info.json").read_text(encoding="utf-8"))
    if fingerprint(sample) != metadata["sample_sha256"]:
        raise ValueError("The prepared sample bytes changed.")
    started = time.monotonic()
    deadline = started + timeout
    with requests.Session() as session:
        session.trust_env = False
        if not state.get("batch_id"):
            if state:
                raise RuntimeError("A previous submission may have succeeded. Do not submit a second batch automatically.")
            state = {"phase": "submitting", "model_version": "vlm", "language": "latin",
                     "uploaded_pages": len(metadata["source_pages"])}
            save_json(state_path, state)
            data = api_json(session, "POST", "/file-urls/batch", token,
                            json={"files": [{"name": "sample.pdf", "is_ocr": True,
                                             "data_id": "probe-" + metadata["sample_sha256"][:20]}],
                                  "model_version": "vlm", "language": "latin",
                                  "enable_table": True, "enable_formula": True})
            batch_id, urls = data.get("batch_id"), data.get("file_urls")
            if not isinstance(batch_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", batch_id):
                raise RuntimeError("MinerU did not return a valid batch ID.")
            state.update(batch_id=batch_id, phase="uploading")
            save_json(state_path, state)
            if not isinstance(urls, list) or len(urls) != 1 or not isinstance(urls[0], str):
                raise RuntimeError("MinerU did not return exactly one upload URL.")
            # Storage requests never receive the API authorization header.
            with sample.open("rb") as content:
                response = session.put(storage_url(urls[0]), data=content,
                                       timeout=(15, 120), allow_redirects=False)
            if response.status_code not in (200, 201, 204):
                raise RuntimeError(f"Sample upload failed (HTTP {response.status_code}).")
            state.update(phase="uploaded")
            save_json(state_path, state)
        elif state.get("phase") == "uploading":
            raise RuntimeError("The previous upload did not finish. Inspect that batch before continuing.")
        batch_id = quote(state["batch_id"], safe="")
        previous = None
        while time.monotonic() < deadline:
            data = api_json(session, "GET", f"/extract-results/batch/{batch_id}", token)
            rows = data.get("extract_result")
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise RuntimeError("The probe batch must return exactly one document.")
            row = rows[0]
            if row.get("file_name") != "sample.pdf":
                raise RuntimeError("The result does not match the uploaded sample.")
            current = row.get("state")
            if current != previous:
                print(f"MinerU state: {current}", flush=True)
                previous = current
            state.update(phase="recognizing", recognition_state=current,
                         elapsed_seconds=round(time.monotonic() - started, 1))
            save_json(state_path, state)
            if current == "failed":
                raise RuntimeError("MinerU reported a parsing failure; the batch ID was retained.")
            if current == "done":
                location = row.get("full_zip_url")
                if not isinstance(location, str):
                    raise RuntimeError("The completed task has no result ZIP URL.")
                temporary = run / "result.zip.part"
                with session.get(storage_url(location), stream=True, timeout=(15, 120),
                                 allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise RuntimeError(f"Result download failed (HTTP {response.status_code}).")
                    count = 0
                    with temporary.open("wb") as output:
                        for chunk in response.iter_content(1024 * 1024):
                            count += len(chunk)
                            if count > MAX_DOWNLOAD or time.monotonic() > deadline:
                                raise RuntimeError("Result download exceeded the probe's size or time limit.")
                            output.write(chunk)
                temporary.replace(run / "result.zip")
                inventory = inspect_archive(run / "result.zip", run)
                state.update(phase="complete", elapsed_seconds=round(time.monotonic() - started, 1))
                save_json(state_path, state)
                return inventory
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise TimeoutError("Polling timed out. Resume this run directory without creating another batch.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--pages", required=True, help="One-based source PDF pages, at most five.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--confirm-upload", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    run, source = args.run_dir.resolve(), args.source.resolve()
    if not run.is_relative_to(ROOT / "data"):
        parser.error("Evidence must remain under this worktree's ignored data directory.")
    if not args.prepare_only and not args.confirm_upload:
        parser.error("Explicit --confirm-upload authorization is required for a live probe.")
    run.mkdir(parents=True, exist_ok=True)
    token, summary = "", {"execution": "failed", "translation_llm_called": False}
    try:
        pages = [int(value) for value in args.pages.split(",")]
        metadata = prepare(source, pages, run)
        summary.update(source_pages=pages, sample_pages=len(pages), model_version="vlm", language="latin")
        if args.prepare_only:
            print(f"Prepared {len(pages)} pages; no network request made. Evidence: {run}")
            return 0
        token = (dotenv_values(ROOT / ".env").get("MINERU_API_TOKEN") or "").strip()
        if not token or token.lower().startswith("bearer "):
            raise ValueError("Configure only the token in MINERU_API_TOKEN in the private .env.")
        summary.update(recognize(run, token, args.timeout), execution="passed")
    except Exception as exc:
        message = str(exc)
        if token:
            message = message.replace(token, "<REDACTED>")
        summary["error"] = re.sub(r"https?://\S+", "<REDACTED_URL>", message)[:500]
        print(f"Probe failed: {summary['error']}", flush=True)
    finally:
        if (run / "sample-info.json").exists():
            metadata = json.loads((run / "sample-info.json").read_text(encoding="utf-8"))
            summary["source_unchanged"] = fingerprint(source) == metadata["source_sha256"]
            if not summary["source_unchanged"]:
                summary["execution"] = "failed"
        if not args.prepare_only:
            save_json(run / "summary.json", summary)
    if summary["execution"] == "passed":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Evidence: {run}")
        return 0
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
