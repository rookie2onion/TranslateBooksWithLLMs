# T03: Continue paused recognition after timeout, stop, or restart without resubmission

Published as [#21](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/21), labeled `ready-for-agent`. Native blocker: [#20](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/20).

## Parent

[Release specification #18](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/18)

## What to build

A reader can stop local recognition work, reach the five-minute local deadline, or restart the application, then continue the same authorized task from the existing Web recovery interface. Where the provider contract and saved phase permit continuation, the application retrieves the existing task/result and continues translation rather than uploading or submitting the book again.

## Acceptance criteria

- [ ] Each recognition attempt or user-requested continuation has one 300-second local budget including transfer/polling, excluding subsequent translation. Retries share that deadline rather than restarting it.
- [ ] Timeout and cooperative user stopping produce truthful, visible local-pause/interruption behavior. No subsequent local translation begins after recognition stopping; the UI does not claim remote cancellation, deletion, or avoided account usage.
- [ ] The existing continuation API and UI load the saved source identity, authorization, phase, remote identifiers, and validated result rather than registering a replacement task. A continuation may grant another local budget for that same task.
- [ ] Reopening the real temporary job store and restoring jobs reproduces safe continuation after process-state loss. Missing source data, expired/unusable result access, and phases that cannot safely continue have actionable errors instead of hidden resubmission.
- [ ] Source/result identity and paragraph mapping are checked before translated segments resume; equal paragraph counts alone do not authorize replay. Changed sources and incompatible legacy native-extraction checkpoints are preserved and reported, not silently overwritten or reused.
- [ ] Repeated or concurrent Continue requests leave at most one active execution for a job, with no duplicate provider submission. Use the existing job owner rather than adding another queue or database.
- [ ] Atomic phase records distinguish a known task from an uncertain submission. If a submission may have succeeded without a returned identifier, the job remains explicitly unknown and no automatic submission retry occurs.
- [ ] An incomplete upload whose transient URL cannot be recovered through the verified contract is reported as unable to continue automatically. Do not persist signed URLs, invent a recovery endpoint, or create another task to disguise this limitation.
- [ ] Rate-limit/transient retries occur only where safe, respect the remaining budget, and do not replay a potentially accepted submission. Terminal provider/configuration failures remain distinct from a local deadline.
- [ ] Paused, failed, or partial jobs retain their existing task-owned recovery data, and successful non-resumable work is not falsely reintroduced as unfinished after restart.
- [ ] New pause, Continue, progress, and error strings work reactively in all seven locales using the existing task UI, without a new test-only API or recognition selector.
- [ ] Primary API-lifecycle tests use a fake monotonic clock, scripted HTTP, fake external LLM, real temporary persistence, and real PDF generation. Cover deadline, stop, restart, duplicate continuation, changed source, known result reuse, ambiguous submission, and unrecoverable upload; verify outgoing submission counts and downloaded artifacts.
