# T05: Finalize whole-book outputs with honest accounting and task-owned cleanup

Published as [#23](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/23), labeled `ready-for-agent`. Native blockers: [#21](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/21), [#22](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/22).

## Parent

[Release specification #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18)

## What to build

A reader finishes a whole-book task and can download the validated translated PDF and a durable content-accounting report even after temporary recognition data is pruned. A partial, interrupted, or failed task remains honestly labeled and recoverable, while completed history and finished outputs retain their existing ownership and retention rules.

## Acceptance criteria

- [ ] Completion requires exactly the expected recognition page coverage and every recognized block accounted for by retained output or a justified exclusion. Empty recognized pages are represented correctly; a sample-only result, missing page, duplicate mapping, or unaccounted block cannot masquerade as whole-book success.
- [ ] The durable report/sidecar survives working-cache pruning and records source/result identity, source-page mapping, recognized/output counts, justified exclusions, images, source-preserved content, and review limitations. It does not claim that accounting proves recognition accuracy or translation of every visible word.
- [ ] The PDF and accounting are published as validated outputs; a failed rebuild or resume does not destroy an already valid published artifact or report successful completion from a stale/missing output.
- [ ] Existing completion classification remains authoritative: failed or unfinished body translation is partial/resumable, not completed, while deliberately source-preserved tables/formulas are not miscounted as failed translation chunks.
- [ ] Recognized image instances, caption/note associations, and paragraph mappings remain stable across translation and continuation. Preview notices, preview suffixes, and untrusted inferred author metadata do not appear in finished artifacts.
- [ ] After validated, non-resumable success, the task's recognition working files are pruned through the existing owner; the completed job row remains usable as history and does not reappear as unfinished after restart.
- [ ] Partial, failed, interrupted, and otherwise recovery-retained tasks keep their source/result/checkpoint data. No cleanup in the PDF translator prematurely destroys data before the final completion verdict.
- [ ] Explicit task deletion and existing 30-day startup cleanup cover the new task-owned recognition files. The UI/report does not promise deletion exactly at the 30-day boundary, and no new cleanup scheduler or permanent cross-task cache is added.
- [ ] Cleanup does not remove finished outputs, another task's files, the user's original external source, private probe/acceptance evidence, or unrelated formats' recovery data. Existing output deletion remains separately user-controlled.
- [ ] Web completion/history, partial/retry, report-download, and error states reflect the actual outcome, with all new strings reactive in seven locales.
- [ ] Primary API tests exercise completed, partial, failed, stopped, resumed, explicitly deleted, and expired jobs using real temporary storage and generated PDFs. Reopen persistence to verify history/recovery and inspect artifacts after working-cache pruning.
- [ ] Existing non-PDF completion, history, checkpoint, output-path, secret-stripping, preview, and PDF regressions remain valid; do not broaden the change into an unrelated cleanup refactor.
