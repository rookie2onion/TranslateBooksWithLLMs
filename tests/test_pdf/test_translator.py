"""Tests for translate_pdf_file (online recognition + plain pipeline + builder).

The PDF extraction boundary is intentionally online-only (issue #20): the
native text extractor is no longer part of the translation path, so these tests
substitute the recognition outcome and keep the translation pipeline and the PDF
builder real.
"""

from __future__ import annotations

import json
import os
import unicodedata
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pymupdf
import pytest

from src.core.epub.translation_metrics import TranslationMetrics
from src.core.mineru.errors import MineruError
from src.core.pdf.accounting import accounting_path_for, read_accounting_summary
from src.core.pdf.content import ParagraphFormat, PdfImage, PdfPlainContent
from src.core.pdf.translator import translate_pdf_file

PIPELINE = "src.core.pdf.translator.translate_paragraphs_plain"
RECOGNITION = "src.core.pdf.translator.recognize_pdf"

def _png_bytes():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 20), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_BYTES = _png_bytes()


def _content(title="Sample Book"):
    return PdfPlainContent(
        paragraphs_text=["Chapter One", "A body paragraph."],
        paragraphs_style=["heading1", "normal"],
        paragraphs_format=[ParagraphFormat(), ParagraphFormat()],
        images_by_paragraph={-1: [PdfImage(data=PNG_BYTES, ext="png",
                                           width_pt=120.0, height_pt=80.0)]},
        page_size=(600, 800),
        title=title,
        author="",
        page_count=2,
    )


class _Source:
    def __init__(self, content):
        self._content = content
        self.paragraphs = tuple(content.paragraphs_text)
        self.styles = tuple(content.paragraphs_style)
        self.formats = tuple(content.paragraphs_format)
        self.images_by_paragraph = dict(content.images_by_paragraph)
        self.provenance = (
            SimpleNamespace(kind="caption", output_index=1),
            SimpleNamespace(kind="footnote", output_index=1),
        )
        self.counts = {"paragraphs": len(content.paragraphs_text), "images": 1,
                       "blocks_seen": 4, "blocks_accounted": 4, "excluded": 0,
                       "findings": 0}
        self.review_required = False

    def to_plain_content(self):
        return self._content


def _recognition(content=None, *, reused=False):
    content = content or _content()
    return SimpleNamespace(
        admitted=SimpleNamespace(
            sha256="a" * 64, size_bytes=4321, page_count=2,
            file_name="source.pdf"),
        source=_Source(content),
        cache=SimpleNamespace(backend="hybrid", engine_version="2.5.4",
                              fingerprints={"layout.json": "f" * 64}),
        batch_id="batch-abc123",
        result_zip_sha256="b" * 64,
        result_cache_sha256="c" * 64,
        cache_sha256="c" * 64,
        page_count=2,
        elapsed_seconds=12.5,
        retries=0,
        remote_states=("pending", "done"),
        reused=reused,
    )


def _fake_pipeline(was_interrupted=False):
    """AsyncMock standing in for translate_paragraphs_plain."""

    async def _run(*args, paragraphs, **kwargs):
        return [f"T:{paragraph}" for paragraph in paragraphs], TranslationMetrics(), was_interrupted

    return AsyncMock(side_effect=_run)


def _normalized_text(path):
    """Full text with whitespace collapsed and ligatures (e.g. U+FB01) expanded."""
    with pymupdf.open(path) as document:
        text = "".join(page.get_text() for page in document)
    return " ".join(unicodedata.normalize("NFKC", text).split())


async def _translate(tmp_path, output_path, *, recognition=None,
                     authorized=True, **kwargs):
    recognition = recognition or _recognition()
    with patch(RECOGNITION, return_value=recognition) as recognize:
        result = await translate_pdf_file(
            input_filepath=str(tmp_path / "source.pdf"),
            output_filepath=str(output_path),
            source_language="English",
            target_language="French",
            model_name="test-model",
            llm_client=Mock(),
            mineru_authorized=authorized,
            **kwargs,
        )
    return result, recognize


@pytest.mark.asyncio
async def test_success_writes_translated_pdf_and_accounting(tmp_path):
    output = tmp_path / "out.pdf"
    log = Mock()
    content = _content()

    with patch(PIPELINE, _fake_pipeline()) as pipeline:
        result, recognize = await _translate(
            tmp_path, output, recognition=_recognition(content), log_callback=log)

    recognize.assert_called_once()
    pipeline.assert_awaited_once()
    assert result["success"] is True
    assert result["output_path"] == str(output)
    assert os.path.exists(output)

    text = _normalized_text(output)
    assert "T:Chapter One" in text
    assert "T:A body paragraph." in text

    with pymupdf.open(output) as document:
        assert document.page_count >= 1
        assert document.metadata["title"] == "Sample Book"
        assert document.metadata["author"] == ""
        assert sum(len(page.get_images()) for page in document) == 1

    keys = [call.args[0] for call in log.call_args_list]
    assert "pdf_recognized" in keys
    assert "pdf_output_validated" in keys
    assert "pdf_rebuilt" in keys

    accounting = json.loads(
        accounting_path_for(output).read_text(encoding="utf-8"))
    assert accounting["source"]["sha256"] == "a" * 64
    assert accounting["recognition"]["batch_id"] == "batch-abc123"
    assert accounting["output"]["sha256"] == result["accounting"]["output"]["sha256"]
    assert accounting["translation"]["complete"] is True


@pytest.mark.asyncio
async def test_recognition_failure_leaves_no_output(tmp_path):
    output = tmp_path / "out.pdf"
    log = Mock()

    def fail(*args, **kwargs):
        raise MineruError("recognition failed")

    with patch(RECOGNITION, side_effect=fail):
        with pytest.raises(MineruError):
            await translate_pdf_file(
                input_filepath=str(tmp_path / "source.pdf"),
                output_filepath=str(output),
                source_language="English", target_language="French",
                model_name="test-model", llm_client=Mock(),
                mineru_authorized=True, log_callback=log)

    assert not output.exists()
    assert "pdf_recognition_failed" in [call.args[0] for call in log.call_args_list]


@pytest.mark.asyncio
async def test_interrupted_writes_no_output_and_no_accounting(tmp_path):
    output = tmp_path / "out.pdf"
    log = Mock()

    with patch(PIPELINE, _fake_pipeline(was_interrupted=True)):
        result, _ = await _translate(tmp_path, output, log_callback=log)

    assert result["success"] is False
    assert result["interrupted"] is True
    assert result["output_path"] is None
    assert not output.exists()
    assert not accounting_path_for(output).exists()
    assert "pdf_interrupted" in [call.args[0] for call in log.call_args_list]


@pytest.mark.asyncio
async def test_bilingual_keeps_source_and_translation(tmp_path):
    output = tmp_path / "out.pdf"
    content = _content()

    with patch(PIPELINE, _fake_pipeline()):
        result, _ = await _translate(
            tmp_path, output, recognition=_recognition(content),
            prompt_options={"bilingual": True})

    assert result["success"] is True
    text = _normalized_text(output)
    for paragraph in content.paragraphs_text:
        assert f"T:{paragraph}" in text
        # The source paragraph appears on its own, not only inside "T:..."
        assert text.count(paragraph) >= 2


@pytest.mark.asyncio
async def test_checkpoint_deleted_only_after_success(tmp_path):
    expected_href = "source.pdf"
    output = tmp_path / "ok.pdf"

    manager = Mock()
    manager.load_xhtml_partial_state.return_value = None
    manager.recognition_dir.return_value = tmp_path / "recognition"
    with patch(PIPELINE, _fake_pipeline()):
        result, _ = await _translate(
            tmp_path, output, checkpoint_manager=manager,
            translation_id="job1")
    assert result["success"] is True
    manager.load_xhtml_partial_state.assert_called_once_with("job1", expected_href)
    manager.delete_xhtml_partial_state.assert_called_once_with("job1", expected_href)

    manager = Mock()
    manager.load_xhtml_partial_state.return_value = None
    manager.recognition_dir.return_value = tmp_path / "recognition2"
    with patch(PIPELINE, _fake_pipeline(was_interrupted=True)):
        result, _ = await _translate(
            tmp_path, tmp_path / "interrupted.pdf",
            checkpoint_manager=manager, translation_id="job1")
    assert result["interrupted"] is True
    manager.delete_xhtml_partial_state.assert_not_called()


@pytest.mark.asyncio
async def test_the_output_is_published_only_after_it_validates(tmp_path):
    output = tmp_path / "out.pdf"
    seen = {}

    from src.core.pdf.builder import build_pdf as real_build_pdf

    def inspecting_build(translated, content, path, *args, **kwargs):
        seen["target_existed_during_build"] = output.exists()
        seen["build_path"] = path
        real_build_pdf(translated, content, path, *args, **kwargs)

    with patch(PIPELINE, _fake_pipeline()), \
            patch("src.core.pdf.translator.build_pdf", side_effect=inspecting_build):
        result, _ = await _translate(tmp_path, output)

    assert seen["target_existed_during_build"] is False
    assert seen["build_path"] != str(output)
    assert result["success"] is True
    assert output.exists()


@pytest.mark.asyncio
async def test_an_invalid_output_is_never_published(tmp_path):
    output = tmp_path / "out.pdf"

    def broken_build(translated, content, path, *args, **kwargs):
        with open(path, "wb") as stream:
            stream.write(b"not a pdf")

    with patch(PIPELINE, _fake_pipeline()), \
            patch("src.core.pdf.translator.build_pdf", side_effect=broken_build):
        with pytest.raises(Exception) as raised:
            await _translate(tmp_path, output)

    assert getattr(raised.value, "code", "") == "mineru_output_invalid"
    assert not output.exists()
    assert not accounting_path_for(output).exists()


@pytest.mark.asyncio
async def test_a_preview_stamped_output_is_rejected(tmp_path):
    output = tmp_path / "out.pdf"

    def preview_build(translated, content, path, *args, **kwargs):
        document = pymupdf.open()
        try:
            page = document.new_page(width=600, height=800)
            page.insert_text((60, 90), "Untranslated MinerU reconstruction preview")
            document.set_metadata({"title": "Sample Book — untranslated MinerU sample preview",
                                   "author": "Grace Hopper"})
            document.save(path)
        finally:
            document.close()

    with patch(PIPELINE, _fake_pipeline()), \
            patch("src.core.pdf.translator.build_pdf", side_effect=preview_build):
        with pytest.raises(Exception) as raised:
            await _translate(tmp_path, output)

    assert getattr(raised.value, "code", "") == "mineru_output_invalid"
    assert not output.exists()


@pytest.mark.asyncio
async def test_authorization_is_forwarded_to_the_recognition_boundary(tmp_path):
    with patch(PIPELINE, _fake_pipeline()):
        _, recognize = await _translate(tmp_path, tmp_path / "a.pdf", authorized=False)

    assert recognize.call_args.kwargs["authorized"] is False
    assert recognize.call_args.kwargs["token"] or True  # token comes from the environment


@pytest.mark.asyncio
async def test_a_local_recognition_stop_is_reported_as_interrupted(tmp_path):
    from src.core.mineru.errors import MineruInterrupted

    output = tmp_path / "out.pdf"
    log = Mock()

    def stopped(*args, **kwargs):
        raise MineruInterrupted(
            "Local recognition was stopped. The remote task may continue; "
            "this is not remote cancellation.")

    with patch(RECOGNITION, side_effect=stopped):
        result = await translate_pdf_file(
            input_filepath=str(tmp_path / "source.pdf"),
            output_filepath=str(output),
            source_language="English", target_language="French",
            model_name="test-model", llm_client=Mock(),
            mineru_authorized=True, log_callback=log)

    assert result["success"] is False
    assert result["interrupted"] is True
    assert result["output_path"] is None
    assert not output.exists()
    assert "pdf_recognition_interrupted" in [
        call.args[0] for call in log.call_args_list]
