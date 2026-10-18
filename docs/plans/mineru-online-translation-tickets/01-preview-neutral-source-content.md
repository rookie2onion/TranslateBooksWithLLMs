# T01: Keep reconstruction previews stable while separating source content

Published as [#19](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/19), labeled `ready-for-agent`. Native blockers: none.

## Parent

[Release specification #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18)

## What to build

Keep the existing cached-source reconstruction commands producing the same promised PDF, EPUB, and acceptance artifacts, while exposing preview-neutral source content for the upcoming translated-book workflow. This is a deliberately small behavior-preserving prefactor, not a new recognition mode or a standalone production feature.

## Acceptance criteria

- [ ] Synthetic validated caches still pass through the existing preview commands to readable source-language PDF, EPUB, and acceptance artifacts, without network or LLM calls.
- [ ] Source adaptation has a canonical view without a generated preview paragraph or preview-only metadata. Preview decoration is applied at the preview boundary rather than being part of the content translated later.
- [ ] Existing preview notices, preview title behavior, paragraph/image accounting, and provenance compatibility remain intact for preview users. EPUB output retains its established byte determinism; do not require byte-identical PDFs where that was not previously promised.
- [ ] Preview-neutral conversion preserves heading styles, caption and footnote content, source mapping, and image anchors, including an image before the first text paragraph.
- [ ] Production-facing conversion does not invent authorship from a nearby paragraph. Existing preview convenience metadata is not silently promoted to trusted bibliographic metadata.
- [ ] No translator-side first-paragraph deletion, string matching of the preview notice, or ad hoc image-index repair is introduced.
- [ ] Cache fingerprints remain unchanged, output-inside-cache protections remain enforced, and private probe/acceptance evidence is untouched.
- [ ] Tests exercise the public conversion and real preview artifacts using synthetic caches. Existing reconstruction, EPUB, acceptance-package, and PDF-builder regressions remain green.
- [ ] Scope remains confined to separating source adaptation from preview presentation; no broad renaming, new renderer, generic provider interface, or recognition-client scaffolding is included.

## Blocked by

None (can start immediately).
