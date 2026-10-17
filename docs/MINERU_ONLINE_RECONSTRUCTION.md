# MinerU Online Reconstruction Preview

Offline, source-language previews built from a cached MinerU online recognition
result. This is the reconstruction slice of the MinerU online effort (issues #14
and #15): it reads only the authorized probe cache and never uploads a document,
calls a provider or invokes a translation LLM. One structural adaptation feeds
two renderers: a reflowed PDF and an EPUB 3 package.

## Requirements

- The project's Python environment (`pip install -r requirements.txt`), which
  provides PyMuPDF and Pillow.
- An authorized cached run directory, for example `data/mineru-online/probe-001`,
  containing `sample-info.json` and MinerU's `result/` directory.

## Command

```bash
# Reflowed PDF preview
python -m src.core.mineru --cache data/mineru-online/probe-001 \
    --output-dir data/mineru-online/recon-001 --format pdf

# EPUB 3 preview (language is explicit; `und` means undetermined)
python -m src.core.mineru --cache data/mineru-online/probe-001 \
    --output-dir data/mineru-online/recon-001-epub --format epub --language de

# Both previews plus the acceptance package
python -m src.core.mineru --cache data/mineru-online/probe-001 \
    --output-dir data/mineru-online/acceptance --format both --language de
```

Each run writes one artifact and one `preview.provenance.json` into the output
directory. `--json` prints a one-object summary instead of the human lines.
`--title` overrides the EPUB package title; otherwise the first recognised
level-1 heading is used. Exit code 1 means the cache was rejected; nothing is
written in that case.

## What is preserved

- Sample reading order from the V2 content list; multi-column pages stay
  column-major.
- Headings (levels 1-3), paragraphs, figures, caption runs and footnotes.
- Figure captions and credits found in `image_caption` / `image_footnote`.
- Page footnotes, including figure captions the recogniser classified as
  footnotes.
- Every image instance, validated and embedded with its source-page box.
- Block provenance: sample index, source PDF page, bounding box and text hash.

## Exclusions, always recorded

- Running headers and typed page numbers are excluded only when the recogniser
  typed them as such, the block sits inside the top 12% band, and its text looks
  like running matter: a short header without terminal punctuation, or a page
  number in digits or Roman numerals. The reason records the text length and how
  often it occurs in the sample.
- Empty recognition records are counted and recorded as `empty_record`.

A numeric top-margin paragraph is kept and flagged `possible_page_number`,
because MinerU sometimes classifies a running folio as a paragraph. Every
recognised block is accounted for: `counts.blocks_accounted` equals
`counts.blocks_seen`, and a block that matches no rule raises
`unaccounted_block` with `review_required: true`.

## What this artifact is not

- Not a translation and not a complete book: the reference sample is five of 198
  source pages.
- Reflowed layout: page count, positions and line breaks intentionally differ
  from the source.
- No table or formula reconstruction and no image redrawing. Those remain later
  phases.

## EPUB package

- EPUB 3 container with `mimetype` first and uncompressed, `META-INF/container.xml`,
  an OPF package document, a navigation document and one XHTML file per section.
- Sections start at each recognised level-1 heading; content before the first
  heading joins the first section, so no synthetic "front matter" chapter is
  invented. Level-2 and level-3 headings become nested navigation entries
  pointing at heading anchors.
- The spine lists the sections in reading order; every manifest item resolves to
  a file inside the package, and every image reference resolves to an embedded
  local asset (deduplicated by content hash, all instances kept in the XHTML).
- Metadata uses trusted input only: the title is the first recognised level-1
  heading or `--title`, and the language is explicit (`--language`, default
  `und`). The EPUB title is never decorated with a preview suffix. If the cache
  has no level-1 heading, the build fails and asks for `--title` instead of
  inventing one. No author is written because the cache carries no trusted
  author field.
- The build is byte-deterministic: fixed ZIP timestamps and a UUID derived from
  the sample hash, language and title.
- No reader application is opened by the build. `reader_check.performed` is
  `false` in the provenance, and visual acceptance remains a human step.

## Acceptance package

`--format both` builds both previews and then collects, under one directory:

```text
report.md              Human-readable checks, content accounting, exclusions,
                       findings, page mapping, limitations and the human checklist.
checks.json            Machine-readable check results, failures, pending items,
                       artifact hashes and the recorded limits.
manifest.json          SHA-256 of every packaged file.
contact-sheet.jpg      The source sample pages, labelled with source PDF page numbers.
pdf/preview.pdf        The reflowed PDF preview and its provenance.
epub/preview.epub      The EPUB 3 preview and its provenance.
```

The checks cover artifact presence, provenance identity against the accepted
cache, cache fingerprints, block accounting, per-content-type coverage, PDF/EPUB
consistency, reading order against the recognised block order (including the
reconstructed PDF page of every paragraph), image integrity, caption and credit
association, exclusion reasons, source-page mapping, structural review status
and the contact sheet. `reader_check` is always `pending`: the build never
reports an unobserved reader or visual check as passed. The command exits
non-zero when any automated check fails.

## Known limitations

- Reading order is MinerU's V2 block order; the adapter does not re-derive
  columns, so an interleaved service order would be reproduced as given.
- Right-to-left source scripts are not re-laid out; the preview assumes a
  left-to-right story layout.
- Author metadata is inferred from the first non-empty paragraph before the first
  title on the same page. It is a convenience, not bibliographic truth; the EPUB
  package does not publish it as `dc:creator`.
- EPUB validation is structural (container, package, manifest, spine, navigation,
  XML well-formedness, relative resources). No `epubcheck` run and no reader-open
  check occurred, so reading-system rendering is not proven.

## Provenance schema

`schema_version` is `1`. Top-level keys:

| Key | Content |
| --- | --- |
| `artifact` | kind, format, `translated: false`, `complete_book: false`, sample page count, notice |
| `engine` | requested model plus returned backend and version |
| `source` | source path, SHA-256, total pages, sample page list, sample SHA-256, cache fingerprints |
| `page_map` | sample index to source PDF page, with page size |
| `counts` | blocks seen and accounted, paragraphs, images, excluded, empty records, findings |
| `pdf` / `epub` | rendition-specific stats: PDF page count and text characters, or EPUB section count and byte size; both carry image and paragraph counts |
| `paragraphs` / `images` | per-element provenance: kind, source type, pages, box, text hash; images also carry cache-relative path and SHA-256 |
| `exclusions` | kind, text, source page, box, reason |
| `findings` | code, message, severity, page and block |
| `reader_check` | whether a reader-open check occurred (always `false` for the offline build) |
| `review_required` | true only for structural findings that need review |

`review_required` is not raised by expected exclusions; it is raised when a
recognised structure contradicts the reconstruction rules, for example a
page-header block sitting outside the top margin.

## Text extraction caveat

The serif story font applies typographic ligatures, so copied text can contain
`ﬁ` or `ﬂ`. The visual text is intact; normalise with NFKC when comparing
extracted text in tests or reports.

## Tests

```bash
pytest tests/test_mineru -q
```

Focused tests build synthetic caches only; the real probe cache stays private
under `data/` and is used for manual evidence. PDF and EPUB tests share the same
fixture package:

- `tests/test_mineru/test_mineru_online_reconstruction.py` — cache validation,
  adaptation and the PDF preview.
- `tests/test_mineru/test_mineru_online_epub.py` — EPUB container, manifest,
  spine, navigation, XHTML, resources, determinism and cache protection.
- `tests/test_mineru/test_mineru_online_acceptance.py` — package layout, check
  results, foreign provenance, tampered cache, escaping, CLI `--format both`.
