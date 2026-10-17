# T04: Deliver tables and formulas as identified source-preserved content

Published as [#22](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/22), labeled `ready-for-agent`. Native blocker: [#20](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/20).

## Parent

[Release specification #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18)

## What to build

A reader submits an authorized PDF containing supported table/formula structures through the same Web workflow and receives a translated PDF that keeps those structures as readable source images. Independent body text, captions, and notes remain translatable; source-preserved content is explicitly identified as untranslated in the rendition and accounting, rather than omitted or falsely claimed as semantically translated.

## Acceptance criteria

- [ ] Supported table/formula fixtures come from a verified online V2 representation, with documented first-party or observed contract evidence. Do not copy the local DocVortex converter schema or invent a type solely to make tests pass.
- [ ] Extend the same loader/source adapter and existing renderer. Prefer supplied source assets; crop from the fingerprint-matched original PDF only when page identity, geometry, and finite non-empty bounds can be established reliably.
- [ ] Recognized table/formula content occupies the correct reading position, including before the first body paragraph where applicable. Images, independent captions, credits, and substantive notes keep their associations and provenance.
- [ ] Every source-preserved block is embedded in the PDF and identified as untranslated. Recognized independent text is translated normally; the application does not redraw pixel text or promise editable/semantic table reconstruction.
- [ ] Source-preserved content is counted separately from translated text and failed translation chunks in the accounting exposed by the existing task/download workflow. Necessary Web summary/error text is reactive across all seven locales.
- [ ] Existing text/block/image/archive bounds remain enforced. Missing assets, wrong-source geometry, invalid crops, and unsupported structures produce explicit failures instead of successful output with dropped blocks.
- [ ] Inline formula support is claimed only if its actual representation and preservation path are verified; otherwise the limitation is explicit. Do not silently discard formula runs or preserve arbitrary body paragraphs as images to hide unsupported structure.
- [ ] Unknown structures remain fail-closed; adding table/formula cases does not turn the loader into an accept-anything parser or change established running-matter exclusion rules.
- [ ] Primary Web/API lifecycle tests run scripted table/formula recognition results through real adaptation, translation orchestration, PDF generation, and download. Inspect actual images/text/accounting, not a mocked renderer result.
- [ ] Synthetic cases cover leading images, adjacent captions/notes, repeated image instances, source-page mapping, invalid bounds, absent assets, unsupported blocks, and source fingerprints. Existing preview and ordinary text/image cases continue to pass without credentials or live calls.
