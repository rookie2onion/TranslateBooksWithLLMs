# MinerU Online PDF Translation: Development Map

Status as of **2026-10-19**: implementation and the agreed personal-use acceptance are complete. [PR #25](https://github.com/rookie2onion/TranslateBooksWithLLMs/pull/25) merged into `origin/main` as `0339be8b18c0598f94c5ad8e3aafee4ba7fd449a` on 2026-10-18. Parent [#18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18) and all six child issues (#19-#24) are closed. Repository checks and Docker Build and Test both passed on that merge commit. No later main commit or open PR was observed during this status check.

The operator accepted the twenty-page live run on 2026-10-17. The five-page and twenty-page results, the `page_footer` fix, and the limits of acceptance are recorded in the [release verification](mineru-online-release-verification.md). The 198-page book, live five-minute pause, runtime browser smoke, and independent human visual review were not exercised and were waived for this personal-use release. Completion does not prove recognition accuracy or translation quality, or authorize another live run.

## Canonical specification and decisions

The self-contained [local spec](mineru-online-translation-spec.md) matches published issue #18. It contains the agreed personal-use scope, 43 user stories, implementation/testing decisions, and exclusions. Domain terminology is recorded in the root glossary; the confirmed architectural boundaries are recorded in ADRs 0001-0003.

In brief: PDF recognition is online-only and needs brief task-specific upload authorization; output is reflowed PDF first, with source-preserved tables/formulas rather than semantic reconstruction. Each recognition attempt/continuation has a five-minute local budget. Task-owned recovery data follows the existing lifecycle, and every new Web string is reactive across seven locales. Other input formats and finished-output retention remain unchanged.

The recognition ceiling is 200 pages and 200,000,000 bytes, with stricter existing limits retained. The current secure Web uploader caps files at 100 MiB (104,857,600 bytes), which this feature does not raise. The fingerprint-matched reference PDF has 198 recorded source pages and measures 50,634,055 bytes, within both ceilings. No automatic splitting is included.

## Published child tickets

The six-ticket breakdown below is the completed delivery map; every linked issue is closed. T-identifiers are retained only as local document identifiers; the linked GitHub issues are authoritative execution tickets. The blocker column preserves the original implementation order, not an active frontier. Publication verified all six native sub-issue links to #18 and the six native blocking edges.

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

There is no open implementation frontier in #19-#24. Follow-up work should have its own scope and evidence. Useful remaining validation is runtime browser smoke and representative visual review of the existing twenty-page artifact; neither has been performed by this documentation sync. A whole-book run and any new provider calls require separate explicit authorization.

Keep the original specification and completed reconstruction tickets as historical requirements. Do not infer that waived gates passed, or reopen completed tickets merely because their original planning text describes the pre-implementation state.

## Code orientation for the next agent

- `src/core/mineru/cache.py` and `result.py` validate V2 pages, blocks, assets, and results. `structure.py` provides neutral source content separately from preview decoration. Sample coverage is not proof of coverage of a larger book.
- `src/core/mineru/admission.py`, `client.py`, `recognition.py`, and `recognition_state.py` own authorization, bounded online recognition, and durable remote identity. Continuation reuses the saved batch/result without hidden resubmission; ambiguous submission fails closed.
- `src/core/pdf/translator.py` connects online recognition to the shared plain-text pipeline and PDF builder. `accounting.py` owns durable content accounting; output validation precedes publication and completion.
- `src/api/blueprints/translation_routes.py` owns task creation/status/interruption/resumption and report access; `src/api/handlers.py` owns worker dispatch and completion. The Web UI exposes per-task authorization, recognition progress, localized errors, and accounting.
- `src/persistence/checkpoint_manager.py` owns task working files, history/pruning, deletion, and 30-day startup cleanup, including task-owned recognition recovery data.
- Synthetic API acceptance tests keep storage, adaptation, orchestration, and rendering real while substituting provider transport, external LLM, and time. They do not prove real browser rendering or semantic translation quality.

## Worktree and validation safety

The 2026-10-19 documentation sync uses `codex/sync-mineru-quality-status` from merge commit `0339be8` in the online worktree. Following explicit operator direction, the former diverged local `main` and its working changes were [archived without integration](quality-archive-2026-10-19.md). Local `main` was recreated from `origin/main`; the MinerU feature is already its ancestor through PR #25. New development should use current `main` or `origin/main`, and must not import the archived quality commit inadvertently. Preserve private acceptance evidence under ignored storage.

Use the project interpreter recorded by `agent.python`; the current environment is `data/online-venv`. Run the configured offline check entrypoint and explicit PDF/MinerU regressions. Default unit checks do not imply every PDF test ran. Tests use synthetic caches/PDFs and temporary task storage, never private source books or real provider settings.

The [service-contract research](mineru-online-service-contract-research.md) preserves primary-source evidence and unknowns. Credentials come only from the existing environment mechanism and must not be displayed or committed. Live sample and full-book calls require separate explicit authorization even after ticket approval and implementation.
