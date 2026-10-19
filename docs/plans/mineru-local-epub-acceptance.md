# Local original-language EPUB acceptance record

## Delivered behavior

The local MinerU command accepts a result JSON or directory and writes an original-language EPUB 3 and reconstruction report without network access, translation, or a probe manifest. It reuses the shared source adapter and EPUB packager. See [usage](../MINERU_LOCAL_EPUB.md) and [specification](mineru-json-to-original-epub-spec.md).

## Real-result evidence

Both supplied result bundles and their original PDFs were processed locally. Source input trees were fingerprinted before and after acceptance and remained byte-identical. Private documents, generated books, rendered pages, and detailed local evidence remain in ignored development data.

| Evidence | Stadtplanung | Legal handout |
| --- | ---: | ---: |
| Recognized / original PDF pages | 198 / 198 | 8 / 8 |
| Recognized blocks accounted | 3,147 / 3,147 | 171 / 171 |
| Unaccounted blocks | 0 | 0 |
| Emitted text paragraphs/items, including captions and notes | 2,109 | 144 |
| Embedded visual instances | 493 | 6 |
| Ordinary visual instances | 331 | 2 |
| Source-preserved tables | 22 | 1 |
| Source-preserved formula paragraphs | 0 | 3 |
| Source-preserved XML-incompatible text/visual regions | 140 | 0 |
| Justified exclusions, including empty merged records and running matter | 620 | 21 |

Generated package XML, XHTML, spine entries, image references, and navigation/fragment links were checked. The multiset of emitted paragraphs/items exactly matches the source model after interpreting explicit inline formatting tags. Every embedded visual instance matches its admitted asset bytes. The source-image report lists the contributing physical regions, not only the first rectangle of a merged paragraph.

Stadtplanung contains XML-invalid recognition characters. Those 140 logical blocks are source images rather than silently rewritten text. Nine include cross-page continuation; additional merged paragraphs cross columns. Physical-block identities, source geometry, and text correspondence are checked before assembling their regions. Figures with distant captions preserve their associated child regions without including intervening unrelated page content. The otherwise missing table on source page 186 is cropped from the bundled original.

This accounting proves disposition of recognized content; it does not prove OCR accuracy. Source-preserved text is visible but not searchable/selectable as text and does not respond to text-size settings.

## Reader checks

The generated EPUBs were opened with the MuPDF EPUB reading engine and reflowed at 600 by 800 points with 12-point text, and 420 by 640 points with 18-point text. Representative cover/front matter, headings, references, columns/dense prose, figures/captions, tables, formulas, and substantive notes were rendered for visual inspection. Stadtplanung source-page samples include 1, 27, 31, 62, 74, 186, 192, and 197; legal-handout samples include 2, 4, 5, and 8.

Reader inspection led to explicit superscript/subscript rendering, exclusion of typed bottom-margin page numbers, source-region coverage fixes, and proportional intrinsic image dimensions. The command report continues to mark human acceptance as pending: agent rendering and package checks are not represented as the user's final reading approval.

## Automated verification

- Twelve focused command-boundary tests cover text/image export, list/caption/note preservation, whole-paragraph formula crops, missing-resource failure without replacing a valid book, source-PDF mismatch, heading/navigation hierarchy, XML-invalid source fallback, report-write failure, merged cross-page pixel preservation, and a caption outside its figure parent's rectangle.
- The five changed source modules pass a focused Mypy check using the project environment with silent import following and missing third-party stubs ignored.
- The complete default offline suite reported **3,534 passed, 1 skipped, 23 deselected, 6 failed**. All six failures are existing progress-characterization snapshots. The unchanged starting commit `b005556` was exported to an isolated directory and reproduced the exact same six failing cases; its characterization file reported 4 passed and 6 failed. No golden files were changed.
- Repository commit checks and independent Standards/Spec review are recorded with the final implementation commit and task completion notes.

## External-code decision

Books_Converter was reviewed at commit `f6b7fc5817413835f9cdbe2d7448e6d481504a17`. Its intrinsic image-size attributes and association-first rendering informed the implementation. No source was vendored and no dependency was added. Direct reuse of its complete pipeline would require a different input adapter, model-assisted structure reconstruction, and changes to its automatic text merging and missing-resource behavior. This milestone retains the existing project pipeline and the agreed source-image policy.
