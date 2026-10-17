# MinerU Online PDF Translation: Offline Release Verification (Ticket #24)

Status: **offline verification complete; release acceptance is not complete.**
Live recognition/translation, the 198-page reference-book run, and human visual
acceptance remain **PENDING**. Issue
[#24](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/24) must stay
open. This report does not claim release completion, recognition accuracy, or
translation quality.

## Scope and limits

- Verification was offline only. No MinerU call, LLM call, upload, or paid
  request was made.
- No provider credential, token, signed URL, or private book content was read,
  printed, or committed. The only token used by the tests is the inert fixture
  value `test-mineru-token`.
- No product code, test, issue, or specification was changed. The only committed
  change from this ticket is this report.
- **Mocked success does not prove real recognition or translation quality.**
  Automated accounting proves coverage and completion of the exercised offline
  pipeline, not the semantic quality of a real provider result.
- Live execution still requires a new explicit authorization identifying the
  document/page scope and the recognition/translation services. Publication of
  this ticket, the parent specification, or an earlier probe authorization is
  not that authorization.

## Environment

| Fact | Value |
|---|---|
| Worktree | `mineru-online-ticket-24` |
| Branch | `ticket/24-release-verification` |
| Base / integration tip | `afb43826af89615384619b636a0a768916b898fb` (`feat(mineru): finalize whole-book outputs with honest accounting`) |
| Merge performed | `git merge --no-edit feat/mineru-online-translation` -> `Already up to date.` (tree unchanged) |
| Interpreter | project `agent.python` (shared across worktrees) -> `data/online-venv/Scripts/python.exe` |
| Python | 3.12.10 (64-bit) |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 |
| Flask | 3.1.3 |
| PyMuPDF | 1.28.2 |
| Offline isolation | `PYTHON_DOTENV_DISABLED=1` for every run |

`data/online-venv` is not inside this worktree; `agent.python` is a shared
repository setting and resolves to the sibling implementation worktree's
environment. That environment has no installed copy of this project, so pytest
and direct scripts import `src` from this worktree. The transient Git-ignored
`data/` artifacts created by the unit gate were removed after the runs; no
`data/` content is part of this commit.

## Commands and actual results

`python` below means the configured interpreter above. All commands ran from
the worktree root.

| Purpose | Command | Result |
|---|---|---|
| Configured project gate | `python scripts/check.py` | exit 0; all changed-file hooks skipped on a clean tree; always-run `pytest (offline unit gate)` **Passed** |
| Offline unit gate explicitly | `python scripts/check.py --unit-only` | **2657 passed, 1 skipped** in 31.25 s; exit 0 |
| Explicit PDF/MinerU regressions (not assumed by the unit gate) | `python -m pytest tests/test_pdf tests/test_mineru -q` | **1034 passed** in 19.22 s; exit 0 |
| Client / provider contract | `python -m pytest tests/test_mineru/test_mineru_online_client.py -q` | **29 passed** in 1.17 s |
| Primary Web/API lifecycle | `python -m pytest tests/test_mineru/test_mineru_online_web_flow.py -q` | **12 passed** in 4.24 s |
| Admission, continuation, non-PDF isolation | `python -m pytest tests/test_mineru/test_mineru_online_admission.py tests/test_mineru/test_mineru_online_continuation.py tests/test_mineru/test_mineru_online_epub.py -q` | **42 passed** in 9.95 s |
| Content preservation | `python -m pytest tests/test_mineru/test_mineru_online_preserved_content.py tests/test_mineru/test_mineru_online_preserved_assets.py tests/test_mineru/test_mineru_online_preserved_accounting.py tests/test_mineru/test_mineru_online_preserved_web_flow.py tests/test_mineru/test_mineru_online_reconstruction.py tests/test_mineru/test_mineru_online_preview_neutral.py -q` | **59 passed** in 4.32 s |
| Completion, cleanup, accounting, recognition state | `python -m pytest tests/test_mineru/test_mineru_online_completion_cleanup.py tests/test_mineru/test_mineru_online_result.py tests/test_mineru/test_mineru_online_recognition.py tests/test_mineru/test_mineru_online_recognition_state.py tests/test_pdf/test_completion_accounting.py tests/test_pdf/test_accounting.py -q` | **78 passed** in 6.06 s |
| UI / i18n | `python -m pytest tests/test_mineru/test_mineru_online_i18n.py tests/test_frontend_i18n.py -q` | **648 passed** in 0.81 s |
| Focused #23-risk API tests (payload ordering, partial resume, live accounting, cleanup) | `python -m pytest tests/test_mineru/test_mineru_online_completion_cleanup.py::test_completed_job_publishes_report_before_status_and_survives_pruning tests/test_mineru/test_mineru_online_completion_cleanup.py::test_partial_body_is_resumable_and_keeps_recovery_data_until_it_completes tests/test_mineru/test_mineru_online_completion_cleanup.py::test_report_and_status_stop_claiming_success_for_a_missing_output tests/test_mineru/test_mineru_online_completion_cleanup.py::test_expired_job_cleanup_removes_recognition_files_not_outputs_or_other_tasks -q` | **4 passed** in 3.14 s |
| Flake confidence, preserved Web flow, 5 isolated runs | `python -m pytest tests/test_mineru/test_mineru_online_preserved_web_flow.py -q` (repeated) | **3 passed** each: 4.00 s, 2.95 s, 3.15 s, 2.32 s, 2.51 s |
| Flake confidence under CPU load | same test file, two background CPU spinners | **3 passed** in 2.55 s |

The default `scripts/check.py` gate and `--unit-only` are not equivalent to the
explicit PDF suite. The PDF/MinerU regression command above was invoked
separately and is reported separately. The integration merge produced no tree
change, so no gate needed to be repeated for it.

After this report was added, `python scripts/check.py` was re-run: the
`end-of-file-fixer` and `trailing-whitespace` hooks passed on the new
documentation, the Python/YAML/isort hooks skipped because no matching changed
files existed, and the always-run pytest offline unit gate passed; exit 0.

## Primary API acceptance seam

The primary seam is
`tests/test_mineru/test_mineru_online_web_flow.py`
(fixture `web`, lines 53-92; main acceptance case `test_authorized_text_pdf_completes_and_downloads_a_translated_book`, lines 160-221).
It enters through the application's own HTTP surface: `/api/upload`,
`/api/translate`, `/api/translation/<id>`, `/api/files/<name>`,
`/api/history`, and `/api/resume/<id>`.

### What is substituted

Only external boundaries:

- **MinerU HTTP transport.**
  `tests/test_mineru/online_fixtures.py:489-497` (`install_fake_http`) replaces
  `requests.Session.request`. The real `MineruClient` still builds requests,
  headers, deadlines, status handling, payload validation, archive extraction,
  and result validation.
- **External LLM.**
  `tests/test_mineru/online_fixtures.py:561-568` (`install_fake_llm`) replaces
  the provider factory. The fake uses the production prompt tag extractor; the
  real prompt construction, plain-text pipeline, translation orchestration, and
  PDF builder run.
- **Time.**
  The shared `FakeClock` (`tests/test_mineru/online_fixtures.py:543-558`)
  advances a monotonic clock and records sleeps where timing behavior is under
  test. The primary Web-flow file polls with short real waits, so it does not
  wait on provider time.

The harness also uses Flask's in-process `test_client` and a recording
`_FakeSocketIO` object. These are transport adapters (HTTP and WebSocket), not
business-logic substitutes: Flask routing, auth, the task worker, state
transitions, and artifact serving are still exercised. The recording SocketIO
object is an observer; it neither drives the pipeline nor any assertion in the
primary acceptance test. No intermediate success result or reconstruction
adapter is mocked.

### What is real

`tests/test_mineru/lifecycle_harness.py:56-86` wires a real Flask app,
`configure_routes`, `register_auth`, `TranslationStateManager`, a real
`CheckpointManager` over a temporary SQLite database, task-owned `uploads/`, an
output directory, and the real `start_translation_job` worker. The exercised
path includes:

- upload validation and secure file admission;
- task creation, status, interruption/continuation, history, and download
  routing;
- temporary SQLite task storage and task-owned working files;
- recognition-result archive validation and the real reconstruction adapter
  (`src/core/mineru/structure.py`);
- the shared plain-text translation orchestration;
- real PDF generation and `validate_pdf_output`;
- the durable accounting sidecar and report download;
- cleanup/retention of task-owned data.

The tests use generated synthetic PDFs and synthetic V2 results. They require no
private book, no real provider credential, and no live network. The fixture token
is the literal `test-mineru-token`; `.env` loading is disabled by
`PYTHON_DOTENV_DISABLED=1`.

### Seam limitation

The Web UI's browser-side event delivery is not exercised by these tests. The
recording SocketIO object proves that events were emitted, not that a browser
rendered them. That is covered only by the static i18n checks below and remains
part of the PENDING human/browser smoke.

## Ticket #24 acceptance status

| # | Acceptance criterion | Status | Evidence / remaining gate |
|---|---|---|---|
| 1 | Run focused client, API-lifecycle, content-preservation, completion, cleanup, and UI checks plus the configured offline gate and explicit PDF/MinerU regressions; record actual results. | **PASS (offline)** | Commands and counts above. `--unit-only` includes `tests/unit` and `tests/test_mineru`; the PDF suite was invoked explicitly and passed 1034 tests. |
| 2 | Confirm the main API seam substitutes only provider transport, external LLM, and time, while real storage, adaptation, orchestration, rendering, and download are exercised; no private book or credential. | **PASS (offline)** | Seam evidence above. Only `requests.Session.request`, the LLM factory, and the clock are substituted. Flask test client and SocketIO recorder are transport stubs, not business mocks. Synthetic data only. |
| 3 | Check locale-key/interpolation parity and switch UI language while authorization, recognition progress, pause, Continue, completion, and error states are displayed; all seven locales; no browser framework added. | **PASS (offline parity/reactivity) / PENDING (runtime switch)** | 648 UI/i18n tests pass. All required keys exist in `en`, `fr`, `es`, `de`, `zh-CN`, `ja`, `ko`; interpolation tokens match English; server error codes have localized entries. Static reactive paths are present. No real browser language switch was executed; see risk (e). |
| 4 | Before any live call, obtain explicit authorization identifying document/page scope and recognition/translation services. | **PENDING** | No live authorization was requested or granted. No live call was made. A prior probe or ticket publication is not treated as authorization. |
| 5 | Credentials only through the existing environment mechanism; missing configuration fails clearly; no fabricated values or printed secrets; no tokens/signed URLs/private content in evidence. | **PASS (offline)** | `test_missing_token_is_rejected_before_any_provider_request` sets an empty `MINERU_API_TOKEN` and gets `mineru_token_missing` with zero provider requests. `.env` disabled. This report is redacted. |
| 6 | After approval, run a bounded live sample first, then confirm authorization for the 198-page book; preserve the five-minute budget; if paused, continue the same remote task without extending or resubmitting. | **PENDING (live)** | Offline pause/continue tests pass, including no resubmission, but no live sample or 198-page run was authorized. |
| 7 | For the real whole-book run, verify source-page coverage, block accounting, source-preserved identification, image/caption/note order, metadata, artifact validity, recoverability/cleanup; reflowed output need not match page count. | **PENDING (live)** | Offline coverage/block/order/artifact/recovery proofs pass; real-book machine verification was not performed. |
| 8 | Inspect representative headings, column transitions, images/captions, footnotes, tables/formulas, and target-language readability; record which visual checks occurred and remain unproven. | **PENDING (human visual)** | No visual inspection of a real translated book occurred. Automated accounting is not semantic-quality proof. |
| 9 | Retain private acceptance artifacts under existing ignored storage; publish only redacted summaries with explicit pass/fail/pending; leave the ticket open when live/human gates are pending. | **PASS (redacted reporting) / PENDING (live artifacts)** | This report is a redacted summary. No private acceptance artifacts exist because no live run occurred. Issue #24 remains open. |
| 10 | Route discovered failures to the responsible slice without expanding scope, weakening admission/asset guards, changing the five-minute budget, or enabling local fallback; do not close or edit the parent specification. | **PASS (routing documented)** | One stats-consistency anomaly is routed below. No fixes, guard changes, budget changes, fallback, or issue edits were made. Parent spec #18 and issue #24 were not edited. |
| 11 | Live execution has an additional explicit user-authorization gate; dependency completion alone is not permission. | **PASS (acknowledged/honored)** | No provider was contacted. Live execution remains separately gated. |

## UI / i18n evidence

The existing offline guards, not a new browser framework, establish parity and
the reactive path:

- `tests/test_mineru/test_mineru_online_i18n.py:48-94` lists the new keys and
  requires every one in all seven locales.
- `:103-115` requires each locale's `{{placeholder}}` set to equal English for
  every new key.
- `:118-124` requires the authorization control and its `data-i18n` markers in
  the template.
- `:140-153` requires every server `mineru_*` error code to have a web
  localization and requires `mineru-errors.js` to match the server code set.
- `:156-193` checks limit placeholders, the source-preserved summary, the
  coverage/empty-page/limitation strings, and both report-download paths.
- `tests/test_frontend_i18n.py:76-105` enforces full locale-key parity for every
  namespace; `:237-311` rejects hardcoded visible template text;
  `:412-447` rejects hardcoded JS text-sink literals.
- Reactive source paths: authorization refresh on locale change
  (`src/web/static/js/translation/batch-controller.js:66`), recognition/progress
  labels (`progress-manager.js:218,451-453`), resume/Continue/pause text
  (`resume-manager.js:27-46,510-514`), completion-card rebuild
  (`translation-tracker.js:902-905`), and history rebuild
  (`history-manager.js:205-208`).
- Legacy `coverage_complete=None` is handled strictly in
  `translation-tracker.js:1039` (`=== true`); the coverage chip is not shown and
  the other accounting fields are guarded by `Number.isFinite`
  (`:1040-1054`). No null dereference is visible in the static path.

What is not proven offline: the actual DOM update when a user toggles the
language selector while each state is on screen. That requires the PENDING
browser smoke (risk e).

## Additional #23-merger risk checks

These were folded into this verification as read-only checks; none changed
production code or tests.

| Risk | Status | Result |
|---|---|---|
| (a) Completion gate false-negatives on normal books | **PASS** | An 8-page synthetic normal book with 2 empty pages, running header/page number exclusions, a substantive page footnote, a table, and an interline formula produced `coverage.complete=true`, `assessment.complete=true`, `source_pages=8`, `empty_pages=[2,6]`, `recognized_blocks=accounted_blocks=14`, `excluded=2`, `tables=1`, `formulas=1`. The same 8-page book through the real Web/API lifecycle ended `status=completed`, `error_code=null`, `coverage_complete=true`, and its sidecar assessment was complete. No `mineru_completion_invalid` false-negative was observed. |
| (b) Legacy sidecar compatibility | **PASS (durable) / CAVEAT (status label)** | A schema-1 sidecar with valid output identity but no coverage section produced `read_accounting_summary.coverage_complete=None` and `assess_pdf_completion -> complete=false, reason=coverage_incomplete`. The real API still listed the job, history reported `accounting_available=true`, and both the translated file and the accounting report downloaded with HTTP 200. No summary/UI null dereference is visible in the static JS. Caveat: the historical job's `status`/history row still reads `completed`, and the completion-card title follows that status; only the coverage chip is suppressed. If "must not claim completion" includes the status label, that is a #23 migration/display question. |
| (c) Retention semantics after restart/aged copy | **PASS** | An aged completed job row plus a recreated task-owned working directory was swept (`deleted_jobs=1`, `cleaned_dirs=1`). The finished PDF downloaded (HTTP 200), its `.accounting.json` remained, and an unrelated `uploads/private-unrelated.txt`, an unrelated `uploads/epub-recovery/checkpoint.json`, and private output evidence all remained. Existing focused cleanup tests also pass. |
| (d) Partial/error ordering and live accounting | **PASS at API level / residual event-order risk** | `GET /api/translation/<id>` computes `accounting` live from the durable sidecar (`src/api/blueprints/translation_routes.py:583-606`), not from the last event. The completed path emits the payload before making status observable (`src/api/handlers.py:1129-1139`). The partial/error paths set DB status before the final `emit_update` (`handlers.py:1089,1201-1203`); the API status poll is still consistent because the sidecar is already written, and the partial/resume API tests pass. The socket-event ordering for partial/error differs from the completed path and is not proven in a browser. |
| (e) Frontend runtime smoke | **PENDING (human/browser)** | Not run. No browser framework was added. Existing pytest only proves static locale markup/parity and source-level `localeChanged` wiring. The required smoke remains: coverage chip, empty-page chip, limitation note, both report-download buttons, and a seven-locale switch without reload while authorization/progress/pause/Continue/completion/error states are visible. |
| (f) Flake confidence | **PASS** | The 3-test `test_mineru_online_preserved_web_flow.py` file passed 5/5 isolated runs (4.00, 2.95, 3.15, 2.32, 2.51 s) and 1/1 under two CPU-spinner jobs (2.55 s). |
| (g) PDF stats and partial->resume counters | **PASS for honest completion / ANOMALY found in progress counters** | `failed_chunks`/`unfinished_chunks` correctly describe the delivered body: partial `1/1`, `body_complete=false`; after successful resume `0/0`, `body_complete=true`; the resume made no provider submission. However, `total_chunks=12` while `completed_chunks=12` on the partial job and `13` after resume (the run log says `13/12`). This is routed below. |

## Discovered failures and routed risks

### Routed failure: `completed_chunks` exceeds `total_chunks` after a partial -> resume retry

Evidence (read-only API run, synthetic one-page long-text book):

- Partial: `total_chunks=12`, `completed_chunks=12`, `failed_chunks=1`,
  `unfinished_chunks=1`, `body_complete=false`.
- After successful resume: `total_chunks=12`, `completed_chunks=13`,
  `failed_chunks=0`, `unfinished_chunks=0`, `body_complete=true`.
- The final run log reports `13/12 chunks`; no new provider submission occurred
  during resume.

This is a counter/progress inconsistency, not a false completion verdict:
`failed_chunks`, `unfinished_chunks`, and `body_complete` remain correct and are
what the completion gate consumes. `_final_pdf_stats`
(`src/core/pdf/translator.py:367-388`) derives those two counters from the
terminal per-segment statuses, so they describe the delivered body rather than a
historical tally. The likely source of the processed-count anomaly is
`src/core/common/plain_text_pipeline.py:774`, which calls
`stats.record_processed()` for a retried segment inside the restored prefix
after `TranslationMetrics.from_dict(resume_stats)` already counted that prefix
as processed. The initial partial count is consistent with "processed"
semantics (12 delivered, one of them source-fallback), not unique-success
semantics.

**Route:** #23 (stats/accounting ownership) with #21 (resume/continuation
behavior) as the context owner. Do not fix here: this ticket routes failures and
does not expand scope. This anomaly does not invalidate the offline coverage,
body-completion, or cleanup evidence, but it should be corrected before the
progress display is treated as a unique-success count.

### Residual risk: partial/error socket payload ordering

The completed path deliberately publishes the payload before the terminal status.
The partial and error paths set the DB status first and emit the final payload
later. `GET /api/translation/<id>` remains consistent because it reads the
sidecar live, and the API-level partial test passes. A browser that reacts to the
status poll before the event payload could briefly show a partial/error state
without the final accounting payload. **Route:** #23 if the UI event ordering
matters for the release; not reproduced as a failing test here.

### Residual risk: legacy completed status label

A pre-#23 completed job with a legacy sidecar still reads `completed` in
status/history. Its durable assessment is `coverage_incomplete`, its summary has
`coverage_complete=None`, and the coverage chip is suppressed. If the release
requires the historical status label itself to stop saying `completed`, that is
a #23 display/migration decision.

## What remains for #24 to stay open

- **Live authorization:** explicit approval identifying the document/page scope
  and the recognition and translation services. A previous probe, the parent
  spec, this ticket, or this report does not authorize a live call.
- **Bounded live sample:** run and record a small authorized sample, including a
  pause at the five-minute local budget and safe continuation of the same remote
  task without extending the budget or resubmitting.
- **198-page reference book:** separate/confirmed authorization, then the
  whole-book run. Verify expected source-page coverage, block accounting,
  source-preserved identification, image/caption/note order, metadata, artifact
  validity, and recoverability/cleanup. Reflowed output need not match the
  source page count or geometry.
- **Human visual acceptance:** inspect representative headings, column
  transitions, images/captions, footnotes, tables/formulas, and target-language
  readability. Record exactly which checks occurred; do not present automated
  accounting as semantic-quality proof.
- **Private artifacts:** retain under existing ignored storage; publish only
  redacted summaries with explicit pass/fail/pending states.
- **Release decision:** leave
  [#24](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/24) open.
  This report is offline evidence only and must not be read as release
  completion.

## Redaction and data handling

No credential, token, signed URL, provider payload, or private document content
is included in this report. The synthetic PDFs, synthetic MinerU V2 archives,
temporary SQLite stores, and temporary output directories used by the tests were
generated locally. The read-only risk checks wrote only under the operating
system's temporary directory and were not committed.
