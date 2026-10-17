# MinerU Online Reconstruction: Progress and Evidence

Status: #14 and #15 are implemented, reviewed and committed (`52fd47a`,
`56ccc1f`) on branch `feat/mineru-online-vlm`. #16 (dual-format acceptance
package) is implemented and awaiting review. No provider call, upload or
translation LLM was used by any step below.

Issues: [#14 PDF](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/14),
[#15 EPUB](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/15),
[#16 acceptance package](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/16).

## Scope

Source-language reconstruction of the authorized five-page sample (source PDF
pages 1, 19, 20, 21 and 22 of 198). The worktree stays isolated from the paused
local-OCR worktree and the quality worktree. Real documents, credentials and the
recognition cache remain under Git-ignored `data/`.

## Ticket status

| Ticket | State | Evidence |
| --- | --- | --- |
| #14 Reconstruct the cached sample as a source-language PDF | Implemented, reviewed, committed (`52fd47a`) | 17 focused tests and 228 PDF regression tests pass; real probe run produced a 10-page PDF; provenance counts match the cache. |
| #15 Export the reconstructed sample as EPUB | Implemented, awaiting code review | 8 focused tests; real probe run produced a 4-section EPUB with 43 paragraphs and 10 images; byte-deterministic output; shared provenance. |
| #16 Dual-format acceptance package | Implemented, awaiting code review | 9 focused tests; real package passes 13 automated checks with `reader_check` pending; report, checks, manifest and contact sheet produced. |

## Decisions

- The V2 content list is the structural source. `layout.json` supplies page
  sizes, the returned backend and the engine version; V1 and the layout blocks
  are not reinterpreted.
- V2 boxes are normalised against a 1000 x 1000 square and converted to source
  points, so image display sizes match the page.
- Exclusions need a stated reason. Running matter must sit in the top 12% band;
  anything ambiguous is retained and flagged instead of dropped.
- Empty records are counted (`empty_record`) rather than silently skipped.
- The preview refuses to write inside the cache directory and renders through
  the existing `build_pdf` story pipeline; no new renderer was introduced.
- The EPUB renderer reuses the same `Reconstruction`: sections start at
  recognised level-1 headings, navigation nests level-2/3 headings, and the spine
  orders the sections. It does not read the generated PDF or re-extract content.
- EPUB metadata uses trusted input only: explicit `--language` (default `und`)
  and the first level-1 heading or `--title`. No `dc:creator` is written because
  the cache has no trusted author field.
- EPUB output is byte-deterministic (fixed ZIP timestamps, UUID derived from the
  sample hash, language and title), and `reader_check.performed` records that no
  reader application was opened.
- `preview.provenance.json` is the shared contract for both formats and #16.

## Review disposition

The two-axis review raised these points; all were resolved before commit except
where noted:

- `Finding` collided with the glossary's translation "Review finding": the
  glossary now defines "Reconstruction finding" separately.
- An empty typed page number outside the top margin was dropped silently: the
  running-matter path now records it, and an accounting invariant guarantees
  every recognised block is emitted, embedded or excluded.
- Recognised image `content` text was discarded: it is now retained as a
  paragraph with an `image_content_retained` finding.
- Image provenance lacked identity: image records now carry the cache-relative
  path and the image SHA-256.
- Header/page-number exclusion was positional only: it now also requires a
  running-text shape and records the occurrence count, so a unique header is
  visible in the exclusion reason.
- Reading order, RTL layout and author inference are documented limitations
  rather than silent assumptions.
- The EPUB review found a synthetic "Front matter" chapter and a preview suffix
  on the package title. Sections now come only from recognised level-1 headings
  (pre-heading content joins the first section), the title is `--title` or the
  first level-1 heading, and the build fails when neither exists.
- EPUB tests now also cover navigation anchor targets, the absence of a
  fabricated front-matter chapter, the trusted-title failure, and the CLI
  `--format epub --language --title` path.
- The acceptance review found a skippable contact sheet, circular reading-order
  evidence, truncated report cells and a dropped review flag. The contact sheet
  is now required (missing source PDF fails), reading order is checked against
  the raw recognised block order and reconstructed PDF pages, report cells are
  HTML/pipes escaped and no longer truncated, and a provenance review flag
  surfaces as a pending `review_status` check.
- `tests/standalone/mineru_online_probe.py` stays untracked and out of this
  commit; it produced the authorized cache and performs uploads, which this
  offline slice must not do.

## Evidence

Focused offline tests (`tests/test_mineru/test_mineru_online_reconstruction.py`):

- cache validation: missing layout, missing image, path escape, page-mapping
  mismatch, unsupported block type;
- adaptation: reading order, heading levels, caption and footnote retention,
  empty records, running-matter exclusion, numeric top-margin paragraph,
  recognised image text and block accounting;
- preview: real PDF with selectable text, two embedded images, provenance
  sidecar, byte-identical cache, network refusal and output-inside-cache refusal;
- review flag: a header outside the top margin raises `review_required`.

Real probe evidence (`data/mineru-online/recon-001/`, Git-ignored):

```text
Wrote data\mineru-online\recon-001\preview.pdf (10 page(s), 43 paragraphs, 10 image(s)).
counts: blocks_seen 65, blocks_accounted 65, blocks_unaccounted 0, paragraphs 43,
        images 10, excluded 14, empty_records 8, findings 4, review_findings 0
exclusions: 8 empty records, 3 running headers, 3 running page numbers
findings: 1 possible_page_number, 3 footnote_retained
review_required: false
```

The 43 paragraphs are 33 body paragraphs, 5 headings, 4 footnotes (3 page
footnotes plus one image credit) and 1 generated notice. The PDF metadata title
is `STADTPLANUNG — untranslated MinerU sample preview`; the notice states the
partial, untranslated scope.

EPUB focused tests (`tests/test_mineru/test_mineru_online_epub.py`) cover the
package container and mimetype entry, OPF metadata and unique identifier,
manifest/spine/navigation consistency, XHTML well-formedness, image references,
deterministic bytes, explicit language and title, the unperformed reader check,
network refusal, cache preservation and output-inside-cache refusal.

Real EPUB evidence (`data/mineru-online/recon-001-epub/`, Git-ignored):

```text
Wrote data\mineru-online\recon-001-epub\preview.epub (3 section(s), 43 paragraphs, 10 image(s)).
counts: blocks_seen 65, blocks_accounted 65, blocks_unaccounted 0, paragraphs 43,
        images 10, excluded 14, empty_records 8, findings 4, review_findings 0
epub: sections 3, images 10, paragraphs 43, bytes 870056
reader_check.performed: false
review_required: false
```

Acceptance focused tests (`tests/test_mineru/test_mineru_online_acceptance.py`)
cover the package layout, passing checks, foreign provenance, a tampered cache,
markdown escaping, network refusal, output-inside-cache refusal and the CLI
`--format both` path.

Real acceptance evidence (`data/mineru-online/acceptance/`, Git-ignored):

```text
Acceptance package: data\mineru-online\acceptance (passed)
14 checks: 13 pass, 1 pending (reader_check), 0 fail
block_accounting: 65 of 65 blocks accounted for
block_coverage: page_footnote 3/3, page_header 3/3, page_number 3/3, paragraph 41/41,
                title 5/5
reading_order: 43 paragraphs in order; EPUB sequence matches; PDF pages 1-10
image_integrity: 10 image instances verified
exclusions_justified: 14 exclusions justified
cache_unmodified: 13 cache files unchanged
contact_sheet: 5 source pages rendered
```

## Not proven

Visual fidelity, whole-book reading order, table and formula handling, image
redrawing and translation quality. The sample has no accepted table case. Reading
order follows the service's V2 block order; the adapter does not re-derive
columns, and the sample's column-major order was only inspected manually.
Right-to-left source layout and typographic-ligature-free text extraction are not
handled. The EPUB package passes structural checks but was not opened in a
reader and was not run through `epubcheck`.

## Next

- Hand the acceptance package to the user for explicit expression-preservation
  review (PDF, EPUB, contact sheet, report).
- Translation, image redrawing, tables/formulas, whole-book coverage and final
  visual acceptance remain later phases; none is claimed.
