# T06: Verify the online PDF release offline, then run separately authorized real acceptance

Published as [#24](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/24), labeled `ready-for-agent`. Native blocker: [#23](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/23).

## Parent

[Release specification #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18)

## What to build

Provide release evidence that a personally operated Web task can proceed from explicit upload authorization to a readable translated PDF, with truthful recovery and whole-book accounting. Start with offline verification; request separate approval before any live sample or reference-book recognition/translation run. This ticket does not grant that approval and must not be marked complete on mocked evidence alone.

## Acceptance criteria

- [ ] Run the focused client, API-lifecycle, content-preservation, completion, cleanup, and UI checks plus the configured offline project gate and explicit PDF/MinerU regressions. Record actual results; the default unit gate is not assumed to include every PDF regression.
- [ ] Confirm that the main API acceptance seam substitutes only external provider transport, external LLM, and time, while real task storage, adaptation, translation orchestration, rendering, and download are exercised. Automated tests require no private book or provider credential.
- [ ] Check locale-key/interpolation parity and switch UI language while authorization, recognition progress, pause, Continue, completion, and error states are displayed. New strings update without reload in all seven supported locales; no browser framework is introduced solely for this release.
- [ ] Before any live call, obtain explicit authorization identifying the document/page scope and recognition/translation services. A previous probe authorization, the parent spec, ticket publication, or approval to implement does not authorize another upload or paid call.
- [ ] Use credentials only through the existing environment mechanism; missing configuration fails clearly without fabricated values or printed secrets. Do not record tokens, signed URLs, or private document content in issues or committed evidence.
- [ ] After approval, run a bounded live sample first, then seek/confirm the appropriate authorization for the 198-page reference book. Preserve the five-minute local budget; if it pauses, demonstrate safe continuation of the same remote task rather than extending the budget or resubmitting.
- [ ] For the real whole-book run, verify expected source-page coverage, block accounting, source-preserved content identification, image/caption/note order, metadata, artifact validity, and recoverability/cleanup behavior. Reflowed output need not match the source page count or geometry.
- [ ] Inspect representative headings, column transitions, images/captions, footnotes, tables/formulas where present, and target-language readability. Record exactly which visual checks occurred and which remain unproven; do not present automated accounting as semantic-quality proof.
- [ ] Retain private acceptance artifacts under existing ignored storage and publish only redacted summaries with explicit pass/fail/pending states. If live approval or human visual acceptance is pending, report that gate and leave this ticket open rather than claiming release completion.
- [ ] Route discovered failures to their responsible implementation slice without expanding scope, weakening admission/asset guards, changing the five-minute budget, or enabling local fallback. Do not close or edit the parent specification as part of this ticket.

Live execution has an additional explicit user-authorization gate; dependency completion alone is not permission to call a provider.
