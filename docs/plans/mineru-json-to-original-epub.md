# MinerU JSON to original-language EPUB

Status: implementation delivered locally; final review and task completion evidence are tracked in the [acceptance record](mineru-local-epub-acceptance.md).

Published specification: [GitHub issue #26](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/26), labeled `ready-for-agent`. The user confirmed the local export command and its EPUB/report artifacts as the primary automated verification seam, with two-document manual reader acceptance. The local specification is [MinerU JSON to original-language EPUB spec](mineru-json-to-original-epub-spec.md).

## Published implementation tickets

The user approved the four-slice breakdown. All tickets are native sub-issues of the specification and labeled `ready-for-agent`; native blocking relationships were verified after publication.

| Ticket | Deliverable | Blocked by |
| --- | --- | --- |
| [T01 / #27](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/27) | Local text/image result to original-language EPUB and report | None |
| [T02 / #28](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/28) | Lists, figure captions, and substantive notes | #27 |
| [T03 / #29](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/29) | Complex-content source images and reliable PDF crops | #27 |
| [T04 / #30](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/30) | Reflowed reading behavior and both-book acceptance | #28, #29 |

The implementation follows this dependency order. Human reader acceptance remains a separate step from automated and agent rendering checks.

## Confirmed decisions

The user accepted all three first-round recommendations on 2026-10-19:

1. Use reflowed layout: multi-column source pages may become a single reading flow, and pagination may change. Preserve reading order, heading hierarchy, and figure-text associations rather than source-page geometry.
2. Accept source images for tables, formulas, and whole formula-containing paragraphs in the first version. Body text and independently recognized captions remain text. Image-backed text is not selectable, searchable as text, or directly available to later EPUB text translation.
3. Deliver a local command producing the original-language EPUB and a short reconstruction report, followed by human reader inspection of the two supplied documents. Web upload and translation integration are later work.
4. Stop the complete export and report the source page/block and reason when necessary content cannot be rendered or reliably preserved, including when both an image asset and a usable source-PDF crop are unavailable. Do not silently omit content or substitute an unexplained placeholder.
5. Preserve recognized wording without automatic spelling correction, dehyphenation guesses, title rewriting, or prose rewriting. Normalize only unambiguous layout whitespace and line breaks while preserving paragraph/list boundaries. Recognition correction is separate work.

The user accepted the two second-round recommendations on 2026-10-19 and subsequently authorized implementation of all four tickets with the implement skill. The user also authorized selecting reusable external code or independently implementing useful layout ideas after reviewing Books_Converter.

## Goal and acceptance boundary

Convert a local MinerU result into a readable original-language EPUB 3, offline and without an LLM. Preserve recognized content, reading order, heading hierarchy, list boundaries, figures and their captions, tables, formulas, and substantive notes.

Fidelity is to recognized wording and source associations. Correct only unambiguous layout whitespace and line breaks; do not silently correct recognition mistakes or guess whether a visible hyphen belongs to a word.

Use reflowed layout as defined in ADR 0002: readers may change font size and viewport width. Source pagination, exact line breaks, and absolute element positions are not acceptance requirements. Styles absent from recognition data cannot be recovered reliably. Do not infer vertical writing from a tall bounding box alone.

## Input and output

- Accept a JSON file or its containing result directory. Resolve referenced images relative to that directory.
- Support the supplied `layout.json` schema directly. A companion content-list V2 file may supply additional semantics only when its relationship to layout blocks can be verified.
- JSON containing image references requires the corresponding image files. An original PDF is optional, but required when a necessary source-region image is missing and must be cropped. Do not promise a complete illustrated book from JSON alone.
- Produce one normally named `.epub` plus a compact reconstruction report containing page/block coverage, exclusions, source-image fallbacks, and unresolved findings.
- Permit explicit book title and source language. Do not invent an author or silently claim that a partial result covers the entire source PDF.

## Existing implementation to reuse

The MinerU cache loader and structural adapter already validate recognized blocks, retain provenance and image anchors, and expose preview-neutral source content. The EPUB preview exporter already packages XHTML, CSS, navigation, metadata, and images into EPUB 3.

The gaps are local raw-result admission without a probe manifest, richer semantic rendering, and a normal export boundary without preview decoration. Extend these owners instead of creating a second conversion pipeline. Keep the current PDF and preview behavior intact.

## Delivery sequence

### 1. Admit raw local results and export a first book

Add a local-result loader alongside the existing cache admission path. Normalize recognized pages and assets into the existing source representation without fabricating online task or authorization metadata. Select one authoritative block layer; never concatenate `para_blocks` and `preproc_blocks`. Retain provider reading order and stable page/block identities. Do not sort all content by coordinates, which can scramble columns.

Factor reusable EPUB rendering/packaging out of the preview boundary only as needed. Add a source-language export entrypoint that does not apply preview notices, title suffixes, or inferred authors. Deliver the first complete text-and-image EPUB early.

Check: the supplied eight-page result converts locally, with no duplicate blocks and no network or translation dependency.

### 2. Preserve semantic structure and visual associations

Extend the existing source representation only where the EPUB needs information it currently loses. Render recognized headings as heading elements, paragraphs as paragraphs, and supported list items as `ol`/`ul` and `li`, preserving numbering and nesting when present. Preserve meaningful inline spans only when the input explicitly provides them.

Keep images, captions, and notes associated in source order; use `figure`/`figcaption` where relationships are known. Retain substantive footnotes at a stable associated location, adding linked references only when recognition provides a reliable relationship. Exclude running headers and page numbers only under the existing justified rules and record exclusions.

For the first version, preserve tables, displayed formulas, and formula-containing paragraphs as existing source images or reliable PDF-region crops. Preserve the entire paragraph when required to avoid losing inline formula context. Do not add a new table-HTML or MathML rendering subsystem for this milestone. The report identifies image-backed content; the original-language book does not need translation-status warnings on every such element. Existing translated exports retain their required untranslated labels.

If an essential block cannot be rendered or preserved, report its page/type and fail the complete export explicitly. Do not silently omit it or produce a success claim.

Check: heading/list structure and figure-caption ordering survive export; every recognized block is emitted or has a justified exclusion.

### 3. Finish reading behavior and the local command

Use a small shared stylesheet: relative typography, proportional image sizing, readable paragraph/list spacing, and captions kept with their figures where reader support permits. Avoid absolute positioning, fixed text heights, and forced source-page breaks. Use page geometry for source association and crop placement, not as the EPUB layout engine.

Split chapters at recognized major headings and generate navigation that follows actual heading levels. Use a single section when no reliable chapter boundary exists. Preserve all content before the first heading. Reuse image deduplication, package metadata, and atomic output writing.

Expose this through the existing MinerU command family with a distinct local input/export mode. Accept an input path, output destination, optional original PDF, title, and language. Keep existing cache-preview invocations compatible. Choose final argument names during implementation rather than adding a second CLI framework.

Check: one documented command creates the book and report from an untouched result directory.

### 4. Verify both real documents and finish

First use the supplied eight-page legal handout. When provided, inspect the Stadtplanung JSON schema and assets before claiming support; use its illustrated, multi-column content as the second acceptance case. Add only compatibility required by observed input differences.

Retain the smallest sufficient automated proof at the export boundary: parse generated XHTML/OPF/navigation, verify internal resource links and spine entries, verify EPUB packaging, and account for source blocks without duplication or unexplained loss. Add focused regression cases only for changed behavior that existing tests do not cover. Preserve XML escaping, local asset-path validation, missing-resource errors, and atomic writes as implementation essentials.

Open both EPUBs in an available reader. Compare representative source regions: cover/front matter, heading transitions, a list, dense text or columns, an image with caption, a table/formula, and a note where present. Check a narrow viewport and enlarged text for clipping, distorted images, and broken reading order. Fix observed defects before declaring completion.

Check: both supplied bundles produce readable EPUBs, all internal references resolve, and the report has no unexplained content loss. Completeness refers to the supplied recognition result unless the original PDF page count is independently verified.

## Scope limits

This milestone includes local loading, reconstruction, EPUB export, minimal usage documentation, and focused proof. It excludes translation, online MinerU submission, Web UI changes, fixed-layout EPUB, exact typography recovery, OCR correction, semantic table/formula reconstruction, performance campaigns, broad security audits, and unrelated test expansion. No issue publication or deployment is required.

## Stadtplanung input inspection

The user supplied the local Stadtplanung result bundle on 2026-10-19. It contains `layout.json`, companion content-list V2 and legacy JSON, an `images/` directory, and the original PDF. The layout reports MinerU 3.4.4, hybrid backend, medium effort, and OCR disabled.

- Both the original PDF and layout contain 198 pages; layout indices run from 0 through 197.
- Authoritative `para_blocks` top-level counts are 1,994 text blocks, 179 titles, 336 images, 212 reference-text blocks, 22 tables, and 10 charts. Nested span counts and the parallel preprocessing layer must not be counted as additional content.
- All 368 unique nonempty image-path references found across layout layers resolve in `images/`; the directory contains 369 files. Layout image paths are bare filenames, so this input requires resolution relative to `images/`, not only the JSON directory. This confirms referenced-file presence, not visual correctness or that every complex block supplies an image reference.
- The companion V2 file contains 198 page entries and represents the 212 reference-text blocks as lists. Inspect list subtypes before choosing ordered/unordered rendering; retain item boundaries without inventing numbering.
- Title levels 1 and 2 and geometric boxes are present. The inspected layout supplies no explicit font family, size, color, bold, or italic metadata. EPUB typography therefore uses consistent defaults rather than claiming to recover the source fonts.

The initial inspection did not constitute conversion or reader acceptance. Both bundles have since been exported and checked; final results and recognition limitations are documented in the [acceptance record](mineru-local-epub-acceptance.md).

## Delivery status

Tickets #27, #28, #29, and #30 are implemented and independently reviewed. Both supplied books pass the local export, package, content-accounting, and agent reader checks recorded in the [acceptance record](mineru-local-epub-acceptance.md). User reading approval remains pending; parent specification #26 remains open. Changes are committed locally without a push.
