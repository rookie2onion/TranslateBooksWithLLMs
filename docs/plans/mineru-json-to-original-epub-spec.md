# Spec: Convert local MinerU results to original-language EPUB

## Problem Statement

Users have already obtained MinerU recognition results and want a readable original-language EPUB without repeating recognition or invoking translation. The current reconstruction command expects an application cache and emits a decorated preview. It does not directly admit the supplied local result bundles or fully preserve semantic lists and figure associations in a normal book export.

The desired fidelity is recognized wording, reading order, and structural relationships. Matching source PDF pagination and typography is not required. Silent content loss, duplicate blocks, detached captions, and unreadable images are unacceptable.

## Solution

Provide one offline command in the existing MinerU command family that accepts a local result JSON or containing directory and produces a normally named EPUB 3 and compact reconstruction report. Reuse existing source adaptation and EPUB packaging, extending their responsible layers where information would otherwise be lost.

Use reflowed layout. Preserve tables, formulas, and entire formula-containing paragraphs as source images when needed. Stop with a source-specific error when necessary content cannot be reliably retained. Do not translate, correct recognition wording, or fabricate missing typography and relationships.

## User Stories

1. As a book owner, I want to supply an existing recognition JSON, so that I can export without repeating recognition.
2. As a book owner, I want to supply its containing directory, so that related resources can be resolved together.
3. As a book owner, I want export to run offline without an LLM or provider key, so that reconstruction has no translation cost.
4. As a book owner, I want original-language text retained, so that the EPUB represents the supplied recognition result.
5. As a reader, I want multi-column content arranged in its recognized reading order, so that I can follow the text naturally.
6. As a reader, I want recognized heading levels preserved, so that the book structure remains clear.
7. As a reader, I want chapter navigation that follows headings, so that I can move through the book.
8. As a reader, I want front matter retained before the first heading, so that introductory content is not lost.
9. As a reader, I want list item boundaries, explicit numbering, and known nesting retained, so that references and enumerations remain understandable.
10. As a reader, I want pictures and charts embedded at their associated positions, so that nearby discussion remains intelligible.
11. As a reader, I want captions and figure notes to remain associated with their visuals, so that their meaning is preserved.
12. As a reader, I want substantive footnotes retained, so that supporting information remains available.
13. As a reader, I want tables and displayed formulas retained as source images in the first version, so that their content survives without semantic reconstruction.
14. As a reader, I want an entire formula-containing paragraph preserved when necessary, so that inline mathematical context is not fragmented.
15. As a book owner, I want an optional original PDF used for reliable source-region crops, so that missing complex-content assets can be recovered.
16. As a book owner, I want an explicit failure when necessary content cannot be retained, so that an incomplete export is not presented as complete.
17. As a reader, I want images to retain their proportions and fit the reading area, so that illustrations remain usable.
18. As a reader, I want text to reflow with a narrow viewport and larger fonts, so that reading is comfortable on different screens.
19. As a book owner, I want to set the title and source language, so that metadata is usable without an invented author.
20. As a book owner, I want a normal book export without preview notices, so that the result is suitable for reading.
21. As a book owner, I want a compact report of pages, blocks, exclusions, and image fallbacks, so that I can assess coverage.
22. As a book owner, I want recognition mistakes left unchanged except for unambiguous layout whitespace, so that conversion does not silently rewrite the source.
23. As an existing user, I want cache preview and PDF behavior preserved, so that this export mode does not break current workflows.
24. As a book owner, I want the supplied legal handout and illustrated Stadtplanung bundle checked in a reader, so that acceptance reflects real documents.
25. As a book owner, I want the input bundle left untouched, so that the recognition results remain reusable.

## Implementation Decisions

- Extend local result admission, preview-neutral source adaptation, the existing EPUB renderer/packager, and the MinerU command entrypoint. Do not create a parallel translation or reconstruction pipeline.
- Admit the supplied MinerU layout schema without requiring a probe manifest or fabricated online task metadata. Accept either the JSON or its containing result directory; resolve bare image filenames in its images directory as well as supported bundle-relative references.
- Use one authoritative recognized block layer. Never concatenate parallel preprocessing and paragraph representations. Preserve stable page/block identities and provider reading order instead of globally sorting coordinates.
- Use companion V2 semantics only with verified correspondence to layout content. Preserve the existing ability to handle validated caches independently of raw local input.
- Extend the source representation only for information the EPUB renderer needs: list boundaries and explicit semantics, heading levels, inline information actually supplied, and visual-caption-note associations. Do not infer styling absent from recognition data or vertical writing from tall boxes alone.
- Render semantic headings, paragraphs, and supported lists. Preserve explicit numbering and nesting without inventing markers. Keep recognized reference-list items distinct even when ordered/unordered semantics are unavailable.
- Keep figures, charts, captions, and notes in their source associations. Add linked footnote references only where the source provides a reliable relationship. Otherwise retain substantive notes at a stable source-associated position without fabricating a link.
- Continue justified running-matter exclusions and record them. Provider-discarded content is not automatically disposable: substantive notes and side text must be retained or receive an explicit justified disposition.
- Preserve tables and formulas using supplied source images or reliable original-PDF crops. Preserve a whole paragraph when required for inline formulas. No new semantic table-HTML or MathML subsystem is required.
- Record image-backed content in the report. The original-language export does not add repeated untranslated warnings; existing translated outputs retain their required identification of untranslated content.
- An original PDF is optional until a necessary crop is required. Validate correspondence before cropping and reuse existing crop behavior where it fits. Never crop from an unrelated source or modify the input bundle; generated working assets belong in output-owned storage.
- Fail complete export with page/block/type and reason when necessary content cannot be rendered or reliably preserved. Missing assets and unsupported essential structures cannot silently disappear behind a successful status. A failure must not replace an existing valid output with a partial book.
- Normalize only unambiguous layout whitespace and line breaks. Preserve paragraph/list boundaries, recognized spelling, and uncertain hyphens. No recognition correction or wording rewrite occurs.
- Separate ordinary export from preview decoration while reusing EPUB packaging. Preserve EPUB 3 container, metadata, manifest, spine, navigation, image deduplication, and atomic output behavior.
- Split chapters at reliable major headings and keep pre-heading content. Use one section if no reliable boundaries exist. Navigation must respect actual heading levels.
- Use a small stylesheet with relative typography, natural flow, and proportional images. Avoid fixed text heights, absolute page positioning, and forced source-page breaks. Source geometry supports association and cropping rather than EPUB pagination.
- Accept an output destination and optional original PDF, book title, and source language. Final flag names follow the existing command conventions. Do not introduce a second CLI framework. Missing title metadata must produce a clear request for an override rather than an invented title or author; unknown language may use the existing undetermined-language value.
- Emit an EPUB and compact report with page/block accounting, justified exclusions, image fallbacks, and findings. Distinguish coverage of the supplied result from independently verified whole-book coverage. Page count agreement alone is not proof of OCR accuracy.
- Preserve XML escaping, local resource-path validation, actionable errors, and atomic writes. These are implementation essentials, not separate security workstreams.

## Testing Decisions

- The user confirmed the local export command producing EPUB plus report as the primary automated verification seam. Test observable artifacts and failure behavior rather than internal helper arrangements.
- Prefer existing offline MinerU EPUB export and reconstruction acceptance tests as prior art for package inspection and accounting. Exercise loader, adapter, and renderer through the export boundary; add a focused lower-level regression only when a concrete changed behavior needs it.
- Verify generated XHTML, package metadata, and navigation parse; internal links and assets resolve; spine entries exist; and EPUB packaging is correct, including the required mimetype entry.
- Verify source wording and order, heading/list structure, visual associations, and per-block dispositions on concise fixtures. Parallel layers must not duplicate content, and essential omissions must fail with useful source information.
- Verify that unresolved necessary content does not publish a partial success or overwrite a valid existing output, and that input bundles remain untouched.
- Perform manual reader acceptance on the supplied eight-page legal handout and 198-page Stadtplanung result. Compare representative front matter, headings, lists, columns/dense text, figures/captions, notes, and complex source-image content where present. Check a narrow viewport and enlarged text for clipping, distortion, and reading-order errors.
- Retain required repository checks for changed behavior. Do not add a broad test campaign, performance benchmark project, security audit, provider integration run, or unrelated regression expansion.

## Out of Scope

- Translation, online recognition, provider configuration, and paid service calls.
- Web UI upload, server integration, and translation workflow integration.
- Fixed-layout EPUB, exact PDF pagination, font recovery, or pixel-exact page replication.
- OCR correction, spelling repair, guessed dehyphenation, and prose editing.
- Semantic table/formula reconstruction and text extraction/redrawing inside image pixels.
- Large-document splitting, quality optimization, and unrelated performance work.
- Implementing this feature, splitting tickets, or creating a PR as part of publishing this specification.

## Further Notes

- All five design recommendations were accepted by the user: reflowed layout, source-image complex content, local-command delivery, explicit failure for unpreservable content, and no automatic recognition correction. The user separately confirmed the verification seam and publishing scope.
- Follow the existing domain definitions of reconstruction, original-language EPUB, reflowed layout, source-preserved content, and whole-book coverage. This continues the reflow decision and reuses the source-preservation strategy without weakening translated-output labeling.
- Both acceptance bundles are available locally, with no need for another upload. Keep private document contents, absolute machine paths, PDFs, and image assets out of the public issue and repository fixtures.
- The inspected Stadtplanung bundle has 198 recognized pages matching its original PDF page count. It includes a companion V2 result, original PDF, and image directory; all 368 nonempty unique layout image references resolve. This is input inspection, not completed conversion or visual acceptance.
- Stadtplanung includes reference text represented as lists in V2, ordinary figures, charts, tables, and substantive notes. Its inspected layout provides geometry and title levels but no explicit font family, font size, color, bold, or italic metadata.
- Implementation should first deliver a complete local text/image export, then finish semantic structure and reading behavior, and finally validate both real documents. No speculative framework or general-purpose schema plugin system is required.
