# Local MinerU results to original-language EPUB

Export an existing MinerU result without network access, recognition, or translation:

```powershell
python -m src.core.mineru --input "D:\Books\recognition-result\layout.json" `
  --output-dir "D:\Books\epub-output" --language de --title "Book title"
```

Run from the repository root using the configured project Python environment. The input may also be the containing result directory. The destination must be outside that input directory. Output is `book.epub` plus `book.report.json`; use separate output directories for different books. Add `--json` for a machine-readable command summary.

## Required input

- A MinerU layout result with page geometry and recognized paragraph blocks. The supplied MinerU 3.4.4 hybrid results are the initial compatibility cases.
- Referenced image files, either bundle-relative or bare filenames under `images/`. Missing images require a reliable original-PDF crop or stop the export.
- A unique bundled `*_origin.pdf` when crops are needed. The exporter checks its page count and displayed-page geometry. An optional `--source-pdf` override must have the same SHA-256 as that bundled original; an external PDF without bundle identity evidence is refused. The layout itself does not supply a source digest, so bundle association is recorded honestly rather than described as independent proof of recognition provenance.

No online cache manifest is required. The paragraph layer is authoritative when present; the parallel preprocessing layer is a fallback, never additional content. Companion V2 files are not needed for the observed reference-list schema: each layout reference block is one item, and its wrapped lines are not separate items.

Current list compatibility is the observed `ref_text` / `reference_list` contract: explicit numbering remains in the text, and reference items have no invented bullets or hierarchy. The supplied results contain no ordered/unordered or nested-list metadata. Other list shapes are refused explicitly until a real supported input contract is available.

Raw local-result admission and online-cache admission deliberately keep their schema decoding and source-identity policies separate. Local missing assets can use a verified bundled original; the online path retains its stricter provider-placeholder and authorization contract. They share normalized block types, crop validation, source adaptation, and EPUB packaging rather than weakening either admission policy to make the decoders identical.

## What the book preserves

The original-language EPUB uses reflowed layout: recognized wording and reading order, heading hierarchy and navigation, reference item boundaries, figures/charts with captions and notes, and substantive page notes. Explicit inline superscript, subscript, bold, and italic tags are retained; ordinary text is escaped. Source fonts absent from recognition data are not reconstructed.

Images retain their proportions. Source columns become a reading flow, and pagination changes with reader settings. Running headers, footers, and typed margin page numbers receive justified exclusions in the report. Substantive discarded content is retained at its source-page position after the page's main content, without invented footnote links.

Tables, displayed formulas, and whole formula-containing paragraphs are source images. A recognition region containing XML-invalid control characters is also cropped from the original PDF rather than silently changing its wording or publishing malformed XHTML. If that crop is unavailable, export stops with a page/block error. Figures with affected captions are preserved as the whole source region so the caption remains associated.

These image-backed regions remain visible but are not selectable/searchable as text, do not enlarge with the text font setting, and are unavailable to later EPUB text translation. Their kinds, reasons, resource names, and preservation methods are recorded in the report. Original-language exports do not insert repeated untranslated labels; translated outputs retain their existing labeling behavior.

For merged text whose source spans extend beyond the parent rectangle, the exporter checks the companion physical-block identities and text correspondence before cropping every contributing region in reading order. Cross-page span geometry must be covered on the appropriate source page. If that mapping is unavailable or inconsistent, export stops. A figure whose caption occupies another column uses separate associated child regions rather than a large rectangle containing unrelated text. The regions are assembled into one source image and listed individually in the report.

## Report and failures

The report includes recognized page/block counts, per-block dispositions, justified exclusions, findings, source-image fallbacks, and available source fingerprints. Coverage means coverage of the supplied recognition result. Page-count agreement with a bundled PDF is reported separately and is not a claim that recognition was accurate.

The exporter does not correct spelling, guess dehyphenation, rewrite headings, or fabricate missing metadata. Supply `--title` if there is no usable recognized title. Unknown source language defaults to `und`, and no author is inferred.

Necessary unsupported content or missing resources fail explicitly. Validation and artifact construction occur before replacing the book; report-write failure also leaves the previous book intact. Generated crops live in temporary output-owned storage and are embedded before that storage is removed. Input JSON, images, and PDF are not modified.

Open the EPUB in your reader and inspect representative headings, lists, figures/captions, notes, and source images at your preferred font size. The command's report always leaves human reader acceptance pending.

## Existing preview commands

The existing `--cache` command still produces sample previews in PDF, EPUB, or both formats. Its default remains PDF. Local `--input` exports EPUB only; its default is EPUB. The new mode does not start the server or integrate with the translation workflow.

Specification: [#26](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/26). Implementation tickets: [#27](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/27), [#28](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/28), [#29](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/29), and [#30](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/30).

## Related implementation reviewed

[Books_Converter](https://github.com/Feplus2/Books_Converter/tree/f6b7fc5817413835f9cdbe2d7448e6d481504a17) was inspected before completing this feature. Its Stage 3 association-first rendering is a useful reference for grouping captions before rendering figures and retaining unassociated substantive notes. This implementation uses the existing shared source model and EPUB packager; it does not vendor that project or add its dependencies. Explicit intrinsic image-size attributes were tried but rejected after a MuPDF reader regression demonstrated clipped large images. Responsive proportional sizing is retained and covered by a reader-level regression through the exported artifact.

Its complete pipeline expects normalized content lists plus reconstructed structure, uses model-assisted structure analysis, and includes automatic dehyphenation. The basic renderer also skips charts and page footnotes, while its richer footnote path depends on additional structure annotations. Direct substitution would therefore require another adapter and changes to the accepted offline, wording-preserving behavior. MathML reconstruction and heuristic footnote linking remain outside this milestone.
