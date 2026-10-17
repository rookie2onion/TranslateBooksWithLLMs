# MinerU Online Reconstruction Preview

Offline, source-language preview built from a cached MinerU online recognition
result. This is the reconstruction slice of the MinerU online effort (issue #14):
it reads only the authorized probe cache and never uploads a document, calls a
provider or invokes a translation LLM.

## Requirements

- The project's Python environment (`pip install -r requirements.txt`), which
  provides PyMuPDF and Pillow.
- An authorized cached run directory, for example `data/mineru-online/probe-001`,
  containing `sample-info.json` and MinerU's `result/` directory.

## Command

```bash
python -m src.core.mineru --cache data/mineru-online/probe-001 \
    --output-dir data/mineru-online/recon-001
```

The command writes `preview.pdf` and `preview.provenance.json`. `--json` prints a
one-object summary instead of the human lines. Exit code 1 means the cache was
rejected; nothing is written in that case.

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
- No table or formula reconstruction, no image redrawing, no EPUB output. Those
  remain later phases.

## Known limitations

- Reading order is MinerU's V2 block order; the adapter does not re-derive
  columns, so an interleaved service order would be reproduced as given.
- Right-to-left source scripts are not re-laid out; the preview assumes a
  left-to-right story layout.
- Author metadata is inferred from the first non-empty paragraph before the first
  title on the same page. It is a convenience, not bibliographic truth.

## Provenance schema

`schema_version` is `1`. Top-level keys:

| Key | Content |
| --- | --- |
| `artifact` | kind, format, `translated: false`, `complete_book: false`, sample page count, notice |
| `engine` | requested model plus returned backend and version |
| `source` | source path, SHA-256, total pages, sample page list, sample SHA-256, cache fingerprints |
| `page_map` | sample index to source PDF page, with page size |
| `counts` | blocks seen, paragraphs, images, excluded, empty records, findings |
| `pdf` | rendered page count, text characters, image count, paragraph count |
| `paragraphs` / `images` | per-element provenance: kind, source type, pages, box, text hash; images also carry cache-relative path and SHA-256 |
| `exclusions` | kind, text, source page, box, reason |
| `findings` | code, message, severity, page and block |
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
pytest tests/test_pdf/test_mineru_online_reconstruction.py -q
```

Focused tests build synthetic caches only; the real probe cache stays private
under `data/` and is used for manual evidence.
