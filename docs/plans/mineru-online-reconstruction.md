# MinerU Online Reconstruction: Progress and Evidence

Status: #14 is implemented and verified offline on branch
`feat/mineru-online-vlm`. #15 (EPUB export) and #16 (dual-format acceptance
package) are pending. No provider call, upload or translation LLM was used by
any step below.

Issue: [#14 Reconstruct the cached MinerU sample as a source-language PDF](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/14).

## Scope

Source-language reconstruction of the authorized five-page sample (source PDF
pages 1, 19, 20, 21 and 22 of 198). The worktree stays isolated from the paused
local-OCR worktree and the quality worktree. Real documents, credentials and the
recognition cache remain under Git-ignored `data/`.

## Ticket status

| Ticket | State | Evidence |
| --- | --- | --- |
| #14 Reconstruct the cached sample as a source-language PDF | Implemented, awaiting code review | 17 focused tests and 228 PDF regression tests pass; real probe run produced a 10-page PDF; provenance counts match the cache. |
| #15 Export the reconstructed sample as EPUB | Pending | Reuses `src.core.mineru.structure.Reconstruction`. |
| #16 Dual-format acceptance package | Pending | Consumes `preview.provenance.json` plus the upcoming EPUB provenance. |

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
- `preview.provenance.json` is the contract #15 and #16 consume.

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
- `tests/standalone/mineru_online_probe.py` stays untracked and out of this
  commit; it produced the authorized cache and performs uploads, which this
  offline slice must not do.

## Evidence

Focused offline tests (`tests/test_pdf/test_mineru_online_reconstruction.py`):

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

## Not proven

Visual fidelity, whole-book reading order, table and formula handling, image
redrawing, EPUB structure and translation quality. The sample has no accepted
table case. Reading order follows the service's V2 block order; the adapter does
not re-derive columns, and the sample's column-major order was only inspected
manually. Right-to-left source layout and typographic-ligature-free text
extraction are not handled.

## Next

- #15: export the same `Reconstruction` as EPUB with shared provenance.
- #16: collect the source contact sheet, PDF, EPUB and a comparison report with
  machine-readable checks.
