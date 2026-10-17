"""
PDF translation entry point.

Wires online recognition, the shared plain-text pipeline and the PDF builder:

    input.pdf -> MinerU online recognition -> SourceContent -> shared plain-text
              pipeline -> build_pdf -> validated, published PDF (+ accounting)

PDF recognition is online-only (issue #20): there is no native text-extraction
fallback, so a scanned or text-layer PDF follows the same path. The native
extractor remains a documented internal utility for tests/tools but is not part
of the translation workflow.

This mirrors ``DocxTranslationAdapter._translate_plain_text`` without the
``GenericTranslationOrchestrator`` layer: PDF has no placeholder path, so the
orchestrator would be dead weight. Segment-level checkpointing reuses the
plain-text partial-state contract unchanged, with the DOCX ``file_href``
convention (the input file's basename).
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import src.config as _config
from src.core.common.plain_text_checkpoint import (
    build_plain_checkpoint_hook,
    delete_plain_checkpoint,
    resume_plain_segments,
)
from src.core.common.plain_text_pipeline import translate_paragraphs_plain
from src.core.mineru.admission import RECOGNITION_BUDGET_SECONDS
from src.core.mineru.errors import MineruError, MineruInterrupted
from src.core.mineru.recognition import RecognitionResult, recognize_pdf
from src.core.mineru.recognition_state import TaskRecognitionStore
from src.core.pdf.accounting import (
    build_accounting,
    validate_pdf_output,
    write_accounting_sidecar,
)
from src.core.pdf.builder import build_pdf
from src.core.pdf.content import PdfError


async def translate_pdf_file(
    input_filepath: str,
    output_filepath: str,
    source_language: str,
    target_language: str,
    model_name: str,
    llm_client: Any,
    max_tokens_per_chunk: int = 450,
    log_callback: Optional[Callable] = None,
    stats_callback: Optional[Callable] = None,
    prompt_options: Optional[Dict] = None,
    max_retries: int = 1,
    context_manager: Optional[Any] = None,
    check_interruption_callback: Optional[Callable] = None,
    checkpoint_manager: Optional[Any] = None,
    translation_id: Optional[str] = None,
    parallel_workers: int = 1,
    mineru_authorized: bool = False,
    mineru_token: Optional[str] = None,
    recognition_budget_seconds: float = RECOGNITION_BUDGET_SECONDS,
    recognition_progress_callback: Optional[Callable[[str], None]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Translate a PDF into a new, reflowed PDF through online recognition.

    Steps:
    1. Load a plain-text partial state for this file when checkpointing is on
    2. Recognize the PDF online (MinerU), or reuse an already validated result,
       and build the neutral ``SourceContent`` (no preview decoration)
    3. Translate the paragraphs through the shared plain-text pipeline,
       resuming at the first unattempted segment when a state exists
    4. Build the reflowed PDF, validate it, publish it atomically and write the
       accounting sidecar

    Args:
        input_filepath: Input PDF file path
        output_filepath: Output PDF file path
        source_language: Source language name
        target_language: Target language name
        model_name: LLM model name
        llm_client: LLM client instance
        max_tokens_per_chunk: Max tokens per chunk
        log_callback: Logging callback function, called as (key, message)
        stats_callback: Statistics callback function (called after each chunk)
        prompt_options: Prompt options (``bilingual`` is honoured by the builder)
        max_retries: Max translation retries (recorded in the checkpoint)
        context_manager: Adaptive context manager (optional)
        check_interruption_callback: Callback to check for interruption (optional)
        checkpoint_manager: Checkpoint manager for partial state (optional)
        translation_id: Translation ID for checkpointing (optional)
        parallel_workers: Number of concurrent chunk translations
        mineru_authorized: The task's explicit MinerU upload authorization.
            False (the default) means the core submission boundary must refuse.
        mineru_token: Token override; resolved from the environment by default.
        recognition_budget_seconds: Local recognition budget (300s by default).
        recognition_progress_callback: Called with the recognition phase name.
        **kwargs: Additional arguments (ignored)

    Returns:
        Dict with success, stats, output_path, accounting (and ``interrupted``
        when the translation was interrupted; no output file is written in that
        case and the checkpoint is kept for a later resume).

    Raises:
        MineruError: A typed recognition/output failure (see ``errors.py``).
        PdfBuildError: The reflowed document cannot be generated. No output file
            is published on any failure.
    """
    # Use filename as file_href for checkpointing (DOCX convention)
    file_href = os.path.basename(input_filepath)
    bilingual = bool(prompt_options.get('bilingual')) if prompt_options else False

    # Check for resume state
    resume_state = None
    if checkpoint_manager and translation_id:
        resume_state = checkpoint_manager.load_xhtml_partial_state(translation_id, file_href)

    store = None
    temporary_workspace = None
    if checkpoint_manager is not None and translation_id:
        store = TaskRecognitionStore(checkpoint_manager, translation_id)
        workspace = store.workspace()
    else:
        workspace = Path(tempfile.mkdtemp(prefix="mineru-recognition-"))
        temporary_workspace = workspace

    token = mineru_token if mineru_token is not None else _config.mineru_api_token()

    try:
        try:
            outcome = await asyncio.to_thread(
                recognize_pdf,
                input_filepath,
                work_dir=workspace,
                authorized=bool(mineru_authorized),
                token=token,
                store=store,
                budget_seconds=recognition_budget_seconds,
                check_interruption=check_interruption_callback,
                progress=recognition_progress_callback,
                log=log_callback,
            )
        except MineruInterrupted as exc:
            # A local stop prevents the rest of this attempt and the translation.
            # It is not remote cancellation, and the checkpoint is kept.
            if log_callback:
                log_callback("pdf_recognition_interrupted", f"🛑 {exc}")
            return {
                'success': False,
                'stats': {},
                'output_path': None,
                'interrupted': True,
                'error_code': exc.code,
            }
        except MineruError as exc:
            if log_callback:
                log_callback("pdf_recognition_failed", f"❌ {exc}")
            raise

        content = outcome.source.to_plain_content()
        paragraph_count = len(content.paragraphs_text)
        n_images = sum(len(images) for images in content.images_by_paragraph.values())
        if log_callback:
            log_callback(
                "pdf_recognized",
                f"📄 PDF: {outcome.page_count} pages recognized online, "
                f"{paragraph_count} paragraphs, {n_images} images"
                f"{' (validated result reused)' if outcome.reused else ''}"
            )
    finally:
        if temporary_workspace is not None:
            shutil.rmtree(temporary_workspace, ignore_errors=True)

    resume_segments, resume_translated = resume_plain_segments(
        resume_state, paragraph_count, log_callback
    )
    checkpoint_hook = build_plain_checkpoint_hook(
        checkpoint_manager=checkpoint_manager,
        translation_id=translation_id,
        file_href=file_href,
        source_language=source_language,
        target_language=target_language,
        model_name=model_name,
        max_tokens_per_chunk=max_tokens_per_chunk,
        max_retries=max_retries,
        paragraph_count=paragraph_count,
        prompt_options=prompt_options,
        bilingual=bilingual,
    )

    translated, stats, was_interrupted = await translate_paragraphs_plain(
        paragraphs=content.paragraphs_text,
        source_language=source_language,
        target_language=target_language,
        model_name=model_name,
        llm_client=llm_client,
        max_tokens_per_chunk=max_tokens_per_chunk,
        log_callback=log_callback,
        stats_callback=stats_callback,
        context_manager=context_manager,
        check_interruption_callback=check_interruption_callback,
        prompt_options=prompt_options,
        parallel_workers=parallel_workers,
        resume_segments=resume_segments,
        resume_translated=resume_translated,
        checkpoint_hook=checkpoint_hook,
    )

    if was_interrupted:
        if log_callback:
            log_callback("pdf_interrupted", "⏸️ PDF translation interrupted - state saved")
        return {
            'success': False,
            'stats': stats.to_dict(),
            'output_path': None,
            'interrupted': True,
        }

    # Build next to the destination, validate, then publish atomically: a
    # partially written or preview-stamped file must never become the task's
    # downloadable output.
    destination = Path(output_filepath)
    temporary_output = Path(str(destination) + ".part")
    try:
        build_pdf(
            translated,
            content,
            str(temporary_output),
            target_language,
            source_language,
            bilingual,
        )
        output_stats = validate_pdf_output(
            temporary_output,
            expected_title=content.title,
            expected_author=content.author,
            expected_paragraphs=len(content.paragraphs_text),
        )
        if log_callback:
            log_callback(
                "pdf_output_validated",
                f"✅ Translated PDF validated: {output_stats.page_count} pages, "
                f"{output_stats.text_chars} characters, "
                f"{output_stats.image_count} images"
            )
        os.replace(temporary_output, destination)
    except Exception:
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
        raise

    accounting = build_accounting(
        recognition=outcome,
        content=content,
        translation_stats=stats.to_dict(),
        output_stats=output_stats,
        output_filename=destination.name,
        source_language=source_language,
        target_language=target_language,
        bilingual=bilingual,
        budget_seconds=recognition_budget_seconds,
    )
    sidecar = write_accounting_sidecar(destination, accounting)

    if log_callback:
        log_callback("pdf_rebuilt", f"📄 PDF rebuilt ({os.path.getsize(destination)} bytes)")
        log_callback("pdf_accounting_written",
                     f"🧾 Accounting report written: {sidecar.name}")

    # The document is complete: drop the segment checkpoint so a later
    # resume of the same job does not replay a stale state.
    delete_plain_checkpoint(checkpoint_manager, translation_id, file_href, log_callback)

    return {
        'success': True,
        'stats': stats.to_dict(),
        'output_path': str(destination),
        'recognition': _recognition_summary(outcome),
        'accounting': accounting,
    }


def _recognition_summary(outcome: RecognitionResult) -> Dict[str, Any]:
    """Compact recognition facts for the live task state (no credentials/URLs)."""
    return {
        'provider': 'mineru-online',
        'pages': outcome.page_count,
        'reused': outcome.reused,
        'result_zip_sha256': outcome.result_zip_sha256,
        'result_cache_sha256': outcome.result_cache_sha256,
        'elapsed_seconds': round(outcome.elapsed_seconds, 3),
    }
