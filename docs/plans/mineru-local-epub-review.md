# Local EPUB implementation review

Review base: `b005556`. Initial frozen implementation: `0d7ecd5`. Standards and Spec were reviewed independently by two read-only agents using the code-review skill. Subsequent corrections are described below.

## Standards

No hard documented-standard violations were found. The implementation follows English-only repository artifacts, keeps credentials outside source and documentation, uses the domain glossary, respects the reflow/source-preservation decisions, and puts tests in the existing test tree. Tooling-enforced formatting is covered by the commit gate.

One judgement-call maintainability concern was reported: local layout decoding and online V2 decoding both handle visual block policy. Their schemas and source-admission contracts differ, so separate decoding is justified, but future semantic policy changes could drift. The local usage document now explains the deliberate distinction: local admission can crop a missing asset from a bundled original; online admission keeps its stricter provider-placeholder and authorization contract. Both routes reuse the normalized block model, crop validator, source adapter, and packager. A generic shared-decoder abstraction was not introduced for these different contracts.

## Spec

One actual acceptance gap was found: a missing ordinary image/chart could successfully use a PDF crop without the reconstruction report identifying that fallback. The report now includes `image_fallbacks` with source page/block, kind, reason, crop method, resource, and regions. Two command-level regressions cover ordinary-image and chart fallback.

An initial concern about arbitrary ordered/nested list forms was reconsidered against the supported-input boundary. The supplied layout has 212 reference-text blocks, each corresponding to a one-item reference list, with no ordering or nesting metadata. Item boundaries and explicit source numbering are preserved without inventing bullets or hierarchy. The reviewer confirmed that unobserved list schemas are a future compatibility boundary, not a blocker for these target inputs. This boundary is explicit in the usage document.

## Reader correction

Agent rendering identified an additional concrete regression in the initial snapshot: intrinsic HTML image width/height attributes caused MuPDF to clip oversized images, despite proportional CSS. Those attributes were removed. A command-to-EPUB-reader regression checks that large images fit the reader width with their original aspect ratio, including a tall portrait image whose vertical continuation reaches the final source pixel. Real-book package and reader checks were repeated after this correction.

## Outcome

Initial review: Standards had zero hard violations and one maintainability judgement call; Spec had one confirmed gap and one subsequently withdrawn compatibility concern. The confirmed gap and the reader regression are corrected. Future schema extensions remain bounded by actual input evidence. Human reading approval remains separate from automated checks and agent rendering.
