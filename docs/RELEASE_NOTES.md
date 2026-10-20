# v1.6.0 — MinerU PDF translation and original-language EPUB

This release consolidates the MinerU online translation workflow and offline EPUB exporter into `main`.

## Highlights

- Translate PDFs through MinerU online recognition, including scanned pages, with explicit per-task upload authorization and a configured `MINERU_API_TOKEN`.
- Pause and resume recognition/translation using durable checkpoints and validated cached results. A completed saved recognition archive can be reused without submitting the document again.
- Preserve figures, captions, notes, supported lists, tables, and formulas with source-block accounting. Tables and formulas remain source images; whole paragraphs containing inline formulas are preserved as clearly marked untranslated images in translated output.
- Export an existing local MinerU layout JSON and its assets to an original-language EPUB 3 plus a conversion report, entirely offline.
- Restore proven printed contents regions as reflowable text and confirmed internal links, without contents thumbnails or another model pass. Unresolved entries remain visible and reported.
- Preserve image proportions and report original-PDF crop fallbacks instead of silently losing unsupported content.

## Getting started

- **Desktop:** download the Windows, macOS Intel, or macOS Apple Silicon archive attached to this release. Configure a translation provider and set `MINERU_API_TOKEN` in the generated `.env` for online PDF translation. No local MinerU model installation is required.
- **Source:** install `requirements.txt`, configure `.env`, and run `python translation_api.py`.
- **Local original-language EPUB:** run `python -m src.core.mineru --input "path/to/layout.json" --output-dir "path/to/epub-output" --language de --title "Book title"`. Keep the output outside the input bundle. See [the local EPUB guide](https://github.com/rookie2onion/TranslateBooksWithLLMs/blob/v1.6.0/docs/MINERU_LOCAL_EPUB.md).

## Validation and limits

The saved 198-page translation completed with page/block accounting. The supplied Stadtplanung local export accounts for all 3,147 recognized blocks and restores 75 valid contents links. A second legal-handout bundle retains all 171 recognized blocks. Normal and narrow EPUB reflow, focused regressions, and independent implementation reviews are recorded in the repository.

PDF/EPUB layout is reflowed, so source pagination and exact typography are not reproduced. Recognition accuracy and translation quality still need human review. Image-preserved regions cannot be searched or translated as EPUB text. Unsupported required content fails explicitly rather than being silently dropped.

Online PDF admission remains limited to 200 pages per task. Longer books currently require separate, locally split volumes; automatic splitting and recombination are not included. See [the operational guidance](https://github.com/rookie2onion/TranslateBooksWithLLMs/blob/v1.6.0/docs/plans/mineru-over-200-pages-research.md).

The archived quality/performance work and disposable contents prototypes are not part of this release. Private books, generated EPUBs, and credentials are not distributed.
