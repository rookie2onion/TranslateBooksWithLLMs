# T02: Translate an authorized text-and-image PDF through the existing Web workflow

Published as [#20](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/20), labeled `ready-for-agent`. Native blocker: [#19](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/19).

## Parent

[Release specification #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18)

## What to build

A reader uploads a small text, scanned, or mixed PDF to the application, explicitly authorizes MinerU upload, and downloads a real reflowed translated PDF through the existing Web task workflow. Demonstrate this complete path offline with scripted provider HTTP and a fake external LLM, while keeping actual validation, task storage, source adaptation, translation orchestration, and PDF generation real.

This establishes the first complete online-only path for supported text-and-image documents. More capable continuation, complex-content preservation, and final release acceptance are separate tickets; safety must not depend on them arriving later.

## Acceptance criteria

- [ ] The existing Web form offers one brief task-specific PDF upload confirmation and no local extraction selector, token editor, or long policy dialog. Server and core submission boundaries require explicit authorization; selecting or locally uploading a document does not grant it.
- [ ] PDF dispatch uses online recognition for both text-layer and scanned inputs, with no implicit native fallback. Existing non-PDF behavior remains unchanged.
- [ ] Missing consent, missing configured MinerU token, corrupt/encrypted PDFs, and excess limits fail clearly with zero provider requests. Enforce at most 200 pages and 200,000,000 bytes while retaining the current stricter 100 MiB Web upload limit.
- [ ] A reusable online client uses the installed HTTP stack and the verified standard upload/poll/download contract, not an import from the manual probe or a new SDK. Validate application success and returned structure, not just HTTP status.
- [ ] Provider credentials are resolved only through the existing environment mechanism and are not forwarded to storage requests, browser payloads, logs, or checkpoints. Validate destinations, redirects, archives, asset paths, and existing resource bounds before consuming returned files.
- [ ] The source fingerprint, task-owned phase, known remote identifiers, and validated result identity have durable atomic records before they are needed for safe continuation. Credentials and signed storage URLs are not persisted in those records.
- [ ] Until safe continuation is implemented, attempted continuation must fail closed rather than silently starting recognition again. Lost or ambiguous submission responses never cause automatic replacement submissions.
- [ ] Even this first slice enforces the 300-second recognition budget, bounded network waits/retries, and cooperative local stopping; a timeout or stop is not called remote cancellation or successful completion. Complete safe continuation is delivered by a subsequent slice.
- [ ] The downloaded PDF contains synthetic translated body text, headings, correctly anchored images, and translated independent captions/notes. It contains no preview notice/suffix or invented author, and the existing language/bilingual options continue to apply where relevant.
- [ ] Recognition results match the admitted source and all expected source pages. A sample cache with incomplete page coverage cannot be accepted as a complete production result.
- [ ] A valid output is made available only after PDF generation and validation; task status and a basic accounting sidecar describe what actually completed. Existing translation partial/error classification is not bypassed.
- [ ] Every new Web string is present in all seven locales, with matching interpolation tokens, and updates on language switch without reload.
- [ ] The primary automated test enters through existing upload/task/status/download APIs with temporary source files and a real temporary job database. Only external HTTP, the external LLM, and time are substituted; the reconstruction adapter, translation pipeline, and PDF builder are not mocked.
- [ ] Synthetic HTTP ZIP/result fixtures match the actual synthetic PDF fingerprint and page count. Supporting contract/admission tests exercise malformed responses, credential separation, unsafe assets, and rejected submissions; no credential, private book, or live call is required.
