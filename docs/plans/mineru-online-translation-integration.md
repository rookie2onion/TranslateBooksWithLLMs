# MinerU Online PDF Translation: Development Map

Status: the release specification is published as [GitHub issue #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18). The user confirmed the primary acceptance seam and approved the six-ticket breakdown. All six child issues (#19-#24) are published, labeled `ready-for-agent`, and linked with native parent/blocking relationships. The parent specification body is unchanged. Implementation has not started; issue publication does not authorize live uploads or paid recognition/translation calls.

## Canonical specification and decisions

The self-contained [local spec](mineru-online-translation-spec.md) matches published issue #18. It contains the agreed personal-use scope, 43 user stories, implementation/testing decisions, and exclusions. Domain terminology is recorded in the root glossary; the confirmed architectural boundaries are recorded in ADRs 0001-0003.

In brief: PDF recognition is online-only and needs brief task-specific upload authorization; output is reflowed PDF first, with source-preserved tables/formulas rather than semantic reconstruction. Each recognition attempt/continuation has a five-minute local budget. Task-owned recovery data follows the existing lifecycle, and every new Web string is reactive across seven locales. Other input formats and finished-output retention remain unchanged.

The recognition ceiling is 200 pages and 200,000,000 bytes, with stricter existing limits retained. The current secure Web uploader caps files at 100 MiB (104,857,600 bytes), which this feature does not raise. The fingerprint-matched reference PDF has 198 recorded source pages and measures 50,634,055 bytes, within both ceilings. No automatic splitting is included.

## Published child tickets

The six-ticket breakdown and blocking edges are approved. T-identifiers are retained only as local document identifiers; the linked GitHub issues are authoritative execution tickets. Publication verified every `ready-for-agent` label, all six native sub-issue links to #18, and the six native blocking edges.

| Local copy | Published issue | What it delivers | Direct native blockers |
|---|---|---|---|
| [T01: Preview-neutral source content](mineru-online-translation-tickets/01-preview-neutral-source-content.md) | [#19](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/19) | A small behavior-preserving prefactor: unchanged preview artifacts plus a neutral source view for translation. | None |
| [T02: Authorized online PDF Web slice](mineru-online-translation-tickets/02-authorized-online-pdf-web-slice.md) | [#20](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/20) | Web authorization through mocked online recognition and real translation orchestration/PDF download for text-and-image documents, with minimum fail-closed safety. | #19 |
| [T03: Pause and continue recognition](mineru-online-translation-tickets/03-pause-and-resume-existing-recognition.md) | [#21](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/21) | Five-minute pause, local stop, restart restoration, and safe continuation of existing remote tasks without hidden resubmission. | #20 |
| [T04: Source-preserved complex content](mineru-online-translation-tickets/04-preserve-complex-source-content.md) | [#22](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/22) | Web-submitted table/formula content reaches the PDF and accounting as identified untranslated source images. | #20 |
| [T05: Honest completion and cleanup](mineru-online-translation-tickets/05-honest-completion-accounting-and-cleanup.md) | [#23](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/23) | Whole-book/partial outcomes, durable report downloads, history, and recovery-safe working-cache cleanup. | #21, #22 |
| [T06: Authorized release acceptance](mineru-online-translation-tickets/06-authorized-release-acceptance.md) | [#24](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/24) | Offline release proof followed by separately authorized sample/whole-book and visual acceptance. | #23 |

Dependency graph: #19 -> #20 -> {#21, #22} -> #23 -> #24. Issues #21 and #22 do not gate each other; that is a logical independence, not permission for parallel writers to share a checkout. Issue #19 is the explicit prefactor exception; subsequent development tickets include their necessary API/UI, persistence, and tests rather than deferring all Web work to a final horizontal ticket. Issue #24 is a verification ticket with a separate live-execution authorization gate.

## Execution rules

Work only the frontier whose blockers are complete. The current frontier is [#19](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/19), using synthetic data and offline tests. Issues #20-#23 likewise require no live provider calls to implement or prove. Issue #24 cannot claim live/visual acceptance while authorization or review is pending.

Do not edit or close the parent specification or reopen the completed reconstruction issues as part of ticket execution. No business code has changed during planning/publication. A transient GitHub connection failure during publication was checked before continuing; all six intended issues were verified without duplicate creation.

## Code orientation for the next agent

- `src/core/mineru/cache.py` owns V2 page/block/asset validation and fingerprints but currently expects a probe-oriented manifest. Preserve probe-cache support while extending production ownership; sample coverage is not whole-book coverage.
- `src/core/mineru/structure.py` currently injects a notice and preview metadata. T01 separates source adaptation from decoration instead of deleting a paragraph in the translator. The PDF builder already supports leading images at anchor `-1`.
- `src/core/pdf/translator.py` owns the extraction -> shared plain-text pipeline -> PDF build path. Replace extraction without creating another translator or renderer, and protect partial checkpoints until the actual completion verdict.
- `src/api/blueprints/translation_routes.py` owns task creation/status/interruption/resumption; `src/api/handlers.py` owns worker dispatch and completion. Existing translation checkpoints alone do not persist remote recognition identity.
- `src/persistence/checkpoint_manager.py` owns task working files, history/pruning, deletion, and 30-day startup cleanup. Attach recognition data to that lifecycle, not a new database, permanent archive, or cleanup scheduler.
- Existing synthetic MinerU fixtures, real-PDF tests, temporary job-history fixtures, upload-security checks, and fake-clock progress tests are relevant prior art. New API acceptance tests keep internal adaptation/pipeline/rendering real and substitute only external HTTP, external LLM, and time.

## Worktree and validation safety

The current checkout remains on the already merged feature branch with only uncommitted planning documents. Start development on a new branch from `origin/main`, carrying these documents; do not merge/rebase/reset the diverged local `main` or import its unrelated quality commit. Do not discard the untracked planning documents or private evidence.

Use the project interpreter recorded by `agent.python`; the current environment is `data/online-venv`. Run the configured offline check entrypoint and explicit PDF/MinerU regressions. Default unit checks do not imply every PDF test ran. Tests use synthetic caches/PDFs and temporary task storage, never private source books or real provider settings.

The [service-contract research](mineru-online-service-contract-research.md) preserves primary-source evidence and unknowns. Credentials come only from the existing environment mechanism and must not be displayed or committed. Live sample and full-book calls require separate explicit authorization even after ticket approval and implementation.
