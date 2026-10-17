# MinerU Online PDF Translation: Offline Release Verification (Ticket #24)

Status: **accepted by the operator on 2026-10-17.** Offline verification
complete; a five-page and a twenty-page authorized live run passed with real
MinerU recognition and DeepSeek translation. The twenty-page run exposed a
`page_footer` contract gap, fixed in `77eb24c`, and the continued run passed.
The operator set the acceptance bar at the twenty-page run; the 198-page
reference run, a live five-minute pause, browser smoke, and independent human
visual review were not exercised and are recorded as waived for this
personal-use release. Issue
[#24](https://github.com/rookie2onion/TranslateBooksWithLLMs/issues/24) is
closed. This report does not claim recognition accuracy or translation quality.

## Scope and limits

- Verification below was offline only. A separate authorized live sample is
  recorded in its own section; no MinerU call, LLM call, upload, or paid request
  was made by the offline suites.
- No provider credential, token, signed URL, or private book content was read,
  printed, or committed. The only token used by the tests is the inert fixture
  value `test-mineru-token`.
- No product code, test, issue, or specification was changed by this
  verification ticket. The only verification-authored change is this report; the
  integration merge brings the reviewed fix commits.
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
| Base / integration tip | `271b2cce580495bde8ced2de6951dbf74cf032c7` (`feat(web): require per-task PDF upload authorization`, 14 fix commits after `afb4382`) |
| Merge performed | `git merge --no-edit feat/mineru-online-translation` -> merge commit `91cb510` (`ort`, 45 files changed) |
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
| Offline unit gate explicitly | `python scripts/check.py --unit-only` | **2748 passed, 1 skipped** in 30.22 s; exit 0 |
| Explicit PDF/MinerU regressions (not assumed by the unit gate) | `python -m pytest tests/test_pdf tests/test_mineru -q` | **1125 passed** in 21.41 s; exit 0 |
| Client / provider contract | `python -m pytest tests/test_mineru/test_mineru_online_client.py -q` | **30 passed** in 0.37 s |
| Primary Web/API lifecycle | `python -m pytest tests/test_mineru/test_mineru_online_web_flow.py -q` | **16 passed** in 4.33 s |
| Admission, continuation, non-PDF isolation | `python -m pytest tests/test_mineru/test_mineru_online_admission.py tests/test_mineru/test_mineru_online_continuation.py tests/test_mineru/test_mineru_online_epub.py -q` | **45 passed** in 9.73 s |
| Content preservation | `python -m pytest tests/test_mineru/test_mineru_online_preserved_content.py tests/test_mineru/test_mineru_online_preserved_assets.py tests/test_mineru/test_mineru_online_preserved_accounting.py tests/test_mineru/test_mineru_online_preserved_web_flow.py tests/test_mineru/test_mineru_online_reconstruction.py tests/test_mineru/test_mineru_online_preview_neutral.py -q` | **59 passed** in 3.88 s |
| Completion, cleanup, accounting, recognition state | `python -m pytest tests/test_mineru/test_mineru_online_completion_cleanup.py tests/test_mineru/test_mineru_online_result.py tests/test_mineru/test_mineru_online_recognition.py tests/test_mineru/test_mineru_online_recognition_state.py tests/test_pdf/test_completion_accounting.py tests/test_pdf/test_accounting.py -q` | **80 passed** in 5.73 s |
| UI / i18n | `python -m pytest tests/test_mineru/test_mineru_online_i18n.py tests/test_frontend_i18n.py -q` | **729 passed** in 0.87 s |
| Targeted post-fix checks (socket i18n, slow upload, credentials, ordering, output phase, timeout/429, stats) | pytest node ids listed under "Targeted fix verification" below | **15 passed** in 3.35 s |
| Per-task authorization + server rejection | `python -m pytest tests/test_mineru/test_mineru_online_admission.py::test_missing_authorization_is_rejected tests/test_mineru/test_mineru_online_web_flow.py::test_missing_authorization_is_rejected_with_zero_provider_requests tests/test_mineru/test_mineru_online_recognition.py::test_recognition_requires_authorization_before_any_provider_request tests/test_mineru/test_mineru_online_recognition.py::test_admitted_continuation_still_requires_authorization tests/test_mineru/test_mineru_online_i18n.py::test_pdf_upload_consent_is_granted_per_task -q` | **5 passed** in 2.26 s |
| Shared atomic-writer/hash refactors and limits parity | `python -m pytest tests/test_mineru/test_mineru_online_recognition_state.py::test_state_is_replaced_atomically tests/test_mineru/test_mineru_online_i18n.py::test_web_limit_fallbacks_match_the_server_admission_limits tests/test_pdf/test_completion_accounting.py tests/test_mineru/test_mineru_online_preserved_accounting.py -q` | **22 passed** in 0.79 s |
| Flake confidence, preserved Web flow, 5 isolated runs | `python -m pytest tests/test_mineru/test_mineru_online_preserved_web_flow.py -q` (repeated) | **3 passed** each: 3.47 s, 3.81 s, 2.58 s, 2.50 s, 2.51 s |
| Flake confidence under CPU load | same test file, two background CPU spinners | **3 passed** in 2.64 s |

The default `scripts/check.py` gate and `--unit-only` are not equivalent to the
explicit PDF suite. The PDF/MinerU regression command above was invoked
separately and is reported separately. The merge from `afb4382` to `271b2cc`
changed 45 files, so every gate and suite above was re-run on the merged tip
rather than reused from the first verification.

After this report was updated, `python scripts/check.py` was re-run: the
`end-of-file-fixer` and `trailing-whitespace` hooks passed on the documentation,
the Python/YAML/isort hooks skipped because no matching changed files existed,
and the always-run pytest offline unit gate passed; exit 0.

## Primary API acceptance seam

The primary seam is
`tests/test_mineru/test_mineru_online_web_flow.py`
(fixture `web`, lines 57-110; main acceptance case
`test_authorized_text_pdf_completes_and_downloads_a_translated_book`, lines 209-270).
It enters through the application's own HTTP surface: `/api/upload`,
`/api/translate`, `/api/translation/<id>`, `/api/files/<name>`,
`/api/history`, `/api/resume/<id>`, and `/api/config` (the last used only for
the credential-leak check).

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
transitions, and artifact serving are still exercised. The SocketIO object is
an observer; the primary acceptance test does not assert on its events, while
the ordering tests install a read-only `on_emit` callback to observe the state
at emit time. No intermediate success result or reconstruction adapter is
mocked.

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
| 1 | Run focused client, API-lifecycle, content-preservation, completion, cleanup, and UI checks plus the configured offline gate and explicit PDF/MinerU regressions; record actual results. | **PASS (offline)** | Commands and counts above. `--unit-only` includes `tests/unit` and `tests/test_mineru` (2748 passed, 1 skipped); the PDF/MinerU suite was invoked explicitly and passed 1125 tests. |
| 2 | Confirm the main API seam substitutes only provider transport, external LLM, and time, while real storage, adaptation, orchestration, rendering, and download are exercised; no private book or credential. | **PASS (offline)** | Seam evidence above. Only `requests.Session.request`, the LLM factory, and the clock are substituted. Flask test client and SocketIO recorder are transport stubs, not business mocks. Synthetic data only. |
| 3 | Check locale-key/interpolation parity and switch UI language while authorization, recognition progress, pause, Continue, completion, and error states are displayed; all seven locales; no browser framework added. | **PASS (offline parity/reactivity) / PENDING (runtime switch)** | 729 UI/i18n tests pass. All required keys exist in `en`, `fr`, `es`, `de`, `zh-CN`, `ja`, `ko`; interpolation tokens match English; server error codes have localized entries. Checkpoint messages now carry a locale key and are resolved at render time. Per-task authorization is wired statically and re-checked server-side. No real browser language switch was executed; see risk (e). |
| 4 | Before any live call, obtain explicit authorization identifying document/page scope and recognition/translation services. | **PENDING** | No live authorization was requested or granted. No live call was made. A prior probe or ticket publication is not treated as authorization. |
| 5 | Credentials only through the existing environment mechanism; missing configuration fails clearly; no fabricated values or printed secrets; no tokens/signed URLs/private content in evidence. | **PASS (offline)** | `test_missing_token_is_rejected_before_any_provider_request` sets an empty `MINERU_API_TOKEN` and gets `mineru_token_missing` with zero provider requests. The web-flow credential check now inspects status, `/api/translations`, `/api/history`, `/` HTML, and `/api/config` for the provider token and its field name without an `or True` escape. `.env` disabled. This report is redacted. |
| 6 | After approval, run a bounded live sample first, then confirm authorization for the 198-page book; preserve the five-minute budget; if paused, continue the same remote task without extending or resubmitting. | **PENDING (live)** | Offline slow-upload, pause/continue, and no-resubmission tests pass, including upload abort inside the 300-second budget; no live sample or 198-page run was authorized. |
| 7 | For the real whole-book run, verify source-page coverage, block accounting, source-preserved identification, image/caption/note order, metadata, artifact validity, recoverability/cleanup; reflowed output need not match page count. | **PENDING (live)** | Offline coverage/block/order/artifact/recovery proofs pass; real-book machine verification was not performed. |
| 8 | Inspect representative headings, column transitions, images/captions, footnotes, tables/formulas, and target-language readability; record which visual checks occurred and remain unproven. | **PENDING (human visual)** | No visual inspection of a real translated book occurred. Automated accounting is not semantic-quality proof. |
| 9 | Retain private acceptance artifacts under existing ignored storage; publish only redacted summaries with explicit pass/fail/pending; leave the ticket open when live/human gates are pending. | **PASS (redacted reporting) / PENDING (live artifacts)** | This report is a redacted summary. No private acceptance artifacts exist because no live run occurred. Issue #24 remains open. |
| 10 | Route discovered failures to the responsible slice without expanding scope, weakening admission/asset guards, changing the five-minute budget, or enabling local fallback; do not close or edit the parent specification. | **PASS (routing + post-fix re-verification)** | The previously routed `completed_chunks` anomaly now passes post-fix. No worker/limit guards, budget, or fallback were changed by this ticket. Residual risks are recorded below. Parent spec #18 and issue #24 were not edited. |
| 11 | Live execution has an additional explicit user-authorization gate; dependency completion alone is not permission. | **PASS (acknowledged/honored)** | No provider was contacted. Live execution remains separately gated. |

## UI / i18n evidence

The existing offline guards, not a new browser framework, establish parity and
the reactive path:

- `tests/test_mineru/test_mineru_online_i18n.py:55-104` lists the new keys
  (including `mineru_task_authorization` and `generating_output`) and requires
  every one in all seven locales.
- `:113-125` requires each locale's `{{placeholder}}` set to equal English for
  every new key.
- `:128-153` requires the three checkpoint-paused `common` keys in every locale
  and keeps their `{{name}}` token aligned with English.
- `:156-165` requires the JS limit fallbacks to equal the server's
  `MAX_PAGES`/`MAX_BYTES`.
- `:168-171` requires the localized `output_generation` progress label.
- `:174-196` requires the checkpoint socket event to carry a locale key and
  forbids raw server prose (`data.message ||`) from bypassing `t()`.
- `:198-220` requires per-task PDF authorization wiring: no batch-level
  `mineruPdfConsent`, one checkbox per queued PDF, `file.mineruAuthorized`
  consumed per task, and `localeChanged` re-render.
- `:237-253` requires every server `mineru_*` error code to have a web
  localization and requires `mineru-errors.js` to match the server code set.
- `:256-291` checks limit placeholders, the source-preserved summary, the
  coverage/empty-page/limitation strings, and both report-download paths.
- `tests/test_frontend_i18n.py:76-105` enforces full locale-key parity for every
  namespace; `:237-311` rejects hardcoded visible template text;
  `:412-447` rejects hardcoded JS text-sink literals.
- Reactive source paths: authorization refresh on locale change
  (`src/web/static/js/translation/batch-controller.js:59`), per-file queue
  rebuild including the PDF consent checkbox (`file-upload.js:161,1107-1130`),
  recognition/progress labels (`progress-manager.js:223,458`),
  resume/Continue/pause text (`resume-manager.js:27-46,514`),
  completion-card rebuild (`translation-tracker.js:902-905`), and history
  rebuild (`history-manager.js:205-208`).
- Legacy `coverage_complete=None` is handled strictly in
  `translation-tracker.js:1039` (`=== true`); the coverage chip is not shown and
  the other accounting fields are guarded by `Number.isFinite`
  (`:1040-1054`). No null dereference is visible in the static path.

What is not proven offline: the actual DOM update when a user toggles the
language selector while each state is on screen, or while a per-task PDF consent
tick is visible. That requires the PENDING browser smoke (risk e). Per-task
authorization wiring is verified statically and its server-side rejection is
covered by tests, not by browser automation.

## Additional #23-merger risk checks

These were folded into this verification as read-only checks; none changed
production code or tests.

| Risk | Status | Result |
|---|---|---|
| (a) Completion gate false-negatives on normal books | **PASS** | An 8-page synthetic normal book with 2 empty pages, running header/page number exclusions, a substantive page footnote, a table, and an interline formula produced `coverage.complete=true`, `assessment.complete=true`, `source_pages=8`, `empty_pages=[2,6]`, `recognized_blocks=accounted_blocks=14`, `excluded=2`, `tables=1`, `formulas=1`. The same 8-page book through the real Web/API lifecycle ended `status=completed`, `error_code=null`, `coverage_complete=true`, and its sidecar assessment was complete. No `mineru_completion_invalid` false-negative was observed. |
| (b) Legacy sidecar compatibility | **PASS (durable) / CAVEAT (status label)** | A schema-1 sidecar with valid output identity but no coverage section produced `read_accounting_summary.coverage_complete=None` and `assess_pdf_completion -> complete=false, reason=coverage_incomplete`. The real API still listed the job, history reported `accounting_available=true`, and both the translated file and the accounting report downloaded with HTTP 200. No summary/UI null dereference is visible in the static JS. Caveat: the historical job's `status`/history row still reads `completed`, and the completion-card title follows that status; only the coverage chip is suppressed. If "must not claim completion" includes the status label, that is a #23 migration/display question. |
| (c) Retention semantics after restart/aged copy | **PASS** | An aged completed job row plus a recreated task-owned working directory was swept (`deleted_jobs=1`, `cleaned_dirs=1`). The finished PDF downloaded (HTTP 200), its `.accounting.json` remained, and an unrelated `uploads/private-unrelated.txt`, an unrelated `uploads/epub-recovery/checkpoint.json`, and private output evidence all remained. Existing focused cleanup tests also pass. |
| (d) Partial/error ordering and live accounting | **PASS at API level / residual event-order risk** | `GET /api/translation/<id>` computes `accounting` live from the durable sidecar (`src/api/blueprints/translation_routes.py:572,614`), not from the last event. The PDF completed path emits the payload before making status observable (`src/api/handlers.py:1138-1143`); non-PDF completion deliberately keeps the historical status-first ordering (`test_completion_emit_order_is_unchanged_for_non_pdf`). The partial/error paths still set DB status before the final `emit_update` (`handlers.py:1093,1208-1209`); the API status poll remains consistent because the sidecar is already written, and the partial/resume API tests pass. Socket-event ordering for partial/error differs from the PDF completed path and is not proven in a browser. |
| (e) Frontend runtime smoke | **PENDING (human/browser)** | Not run. No browser framework was added. Existing pytest proves static locale markup/parity, source-level `localeChanged` wiring, and the per-task PDF consent markup/flow; the server rejection path is covered by tests. The required smoke remains: coverage chip, empty-page chip, limitation note, both report-download buttons, per-task consent ticks, and a seven-locale switch without reload while authorization/progress/pause/Continue/completion/error states are visible. |
| (f) Flake confidence | **PASS** | The 3-test `test_mineru_online_preserved_web_flow.py` file passed 5/5 isolated runs (3.47, 3.81, 2.58, 2.50, 2.51 s) and 1/1 under two CPU-spinner jobs (2.64 s). |
| (g) PDF stats and partial->resume counters | **PASS (post-fix)** | `failed_chunks`/`unfinished_chunks` correctly describe the delivered body: partial `1/1`, `body_complete=false`; after successful resume `0/0`, `body_complete=true`; no provider resubmission. The earlier `completed_chunks=13` / `total_chunks=12` regression is fixed: the post-fix run is `12/12` both before and after resume. New regression test `test_resuming_a_partial_pdf_keeps_chunk_accounting_consistent` asserts `completed_chunks == total_chunks`, failed/unfinished zero, and one submission. |

## Targeted fix verification (integration `271b2cc`)

Every fix area requested for re-verification is green offline. The checks below
are static/source-level, server-side, or API-level; none is a browser execution.

| Check | Status | Evidence |
|---|---|---|
| Socket checkpoint i18n keys resolve through `t()`; no raw `data.message` fallback | **PASS (static path)** | `src/api/handlers.py` emits `message_key` + `message_params` for translation pause (`common:checkpoint_translation_paused`), rate-limit pause (`common:checkpoint_rate_limited`), and local recognition pause (`common:checkpoint_recognition_paused`). `src/web/static/js/core/websocket-manager.js:51-58` resolves `data.message_key` through `t(...)` and uses only `common:checkpoint_created_default` as fallback; `data.message ||` is gone. `tests/test_mineru/test_mineru_online_i18n.py:128-153,174-196` covers all seven locales, the `{{name}}` token, and the no-raw-prose guard. Runtime language-switch re-render remains part of the PENDING browser smoke. |
| Slow-upload budget | **PASS** | `tests/test_mineru/test_mineru_online_client.py:352-389` aborts a streamed upload inside the 300-second deadline with one attempt. The Web-level `test_a_slow_upload_ends_at_the_budget_and_pauses_instead_of_completing` (`test_mineru_online_continuation.py:284`) observes `interrupted` + `mineru_recognition_timeout`, `accounting=None`, no output, zero LLM calls, one submission, `phase=upload_failed`, and `elapsed_seconds <= 300`. |
| Credential assertions without `or True` on browser-visible surfaces | **PASS** | `test_mineru_online_web_flow.py:181-205` now checks the provider token and the `mineru_api_token` field against the status payload, `/api/translations`, `/api/history`, the rendered `/` HTML, and `/api/config`; the old `or True` assertion was removed from the primary case. The report also notes one remaining unrelated weak assertion at `tests/test_pdf/test_translator.py:448` (token forwarded to the recognition boundary, not a browser-visible payload); it was not changed by this verification ticket. |
| Non-PDF completion ordering and DB status restored | **PASS** | `test_completion_emit_order_is_unchanged_for_non_pdf` observes the terminal status already set at emit time; `test_a_failed_non_pdf_job_keeps_the_startup_sweep_contract` asserts the failed non-PDF DB row remains `running` for startup recovery. The PDF-only payload-first branch is explicit in `handlers.py:1138-1143`; the PDF test proves a poller cannot see `completed` before the payload. |
| `output_generation` phase observed before `completed` with validated accounting | **PASS** | `test_pdf_reports_a_distinct_output_generation_phase` observes `output_generation` after `recognizing`/`validating` and before the terminal event, and the terminal payload carries `accounting.body_complete=true`. Source: `src/core/pdf/translator.py:298`; label `translation:generating_output` is tested at `test_mineru_online_i18n.py:168-171`. |
| Pre-send timeout / 429 classification (retryable, not `submission_unknown`) | **PASS at client, orchestrator, and Web level** | Client: `test_a_pre_send_timeout_proves_no_request_was_issued` proves a pre-send `MineruTimeout` issues no request, leaves `phase=admitted`, and allows a later one-time submission. 429: `test_a_rate_limited_submission_is_a_definite_rejection` raises `MineruSubmissionRejected` with no replay; `test_a_rate_limited_submission_is_recorded_as_retryable` records `mineru_submission_rejected` in `admitted`, then permits one retry; `test_a_rate_limited_submission_is_retryable_through_continue` covers the Web/Continue path. |
| Partial -> resume -> completed stats | **PASS (post-fix)** | New regression test `test_resuming_a_partial_pdf_keeps_chunk_accounting_consistent` (`test_mineru_online_continuation.py:1141-1176`) asserts `completed_chunks == total_chunks`, `failed_chunks == 0`, `unfinished_chunks == 0`, and an unchanged submission count. The read-only API check now reports `12/12` after resume (previously `13/12`), with no resubmission. |
| Per-PDF (per-task) authorization UI wiring + server rejection | **PASS (static + server) / PENDING (browser)** | `test_pdf_upload_consent_is_granted_per_task` requires the per-file checkbox (`file.mineruAuthorized`, `mineru_task_authorization`), no batch-level `mineruPdfConsent`, per-task consumption in `batch-controller.js`, and local re-render (`file-upload.js:161,1107-1130`). Server rejection tests pass: missing authorization in admission and Web flow, recognition and continuation without authorization, with zero provider requests. Browser execution of the checkbox remains unrun. |
| Shared hashing/atomic-writer refactors and limits parity | **PASS** | `src/utils/hashing.py` and `src/utils/atomic_io.py` are now the single implementations used by admission, cache, recognition, result, acceptance, accounting, preview, and recognition state. `test_state_is_replaced_atomically` proves a failed write leaves the previous state intact and no `.part` file; `test_pdf/test_completion_accounting.py` and `test_mineru_online_preserved_accounting.py` pass (14 + 6 tests). `test_web_limit_fallbacks_match_the_server_admission_limits` ties the JS fallbacks to `MAX_PAGES`/`MAX_BYTES`; 22/22 targeted refactor/accounting tests pass. |

### Post-fix status and residual risks

No confirmed offline failure remains on integration tip `271b2cc`. The previous
routed `completed_chunks` anomaly is resolved, and the regression test now pins
the fixed behavior. Residual risks that are not release blockers for the offline
gate:

- **Partial/error socket payload ordering.** The PDF completed path publishes
  the payload before the terminal status, but partial/error paths still set the
  DB status before the final `emit_update`. `GET /api/translation/<id>` remains
  consistent because it reads the sidecar live. Route to #23 if browser event
  ordering matters for the release; not reproduced as a failing test here.
- **Legacy completed status label.** A pre-#23 completed job with a legacy
  sidecar still reads `completed` in status/history, while its durable
  assessment is `coverage_incomplete` and its coverage chip is suppressed. If
  the release requires the historical status label itself to stop saying
  `completed`, that is a #23 display/migration decision.
- **Remaining weak test assertion.** `tests/test_pdf/test_translator.py:448`
  still ends a token-forwarding assertion with `or True`; it is not a
  browser-visible credential surface and is outside this ticket's fix scope.

## Live sample acceptance (authorized)

The operator authorized one bounded live sample on 2026-10-17: the five-page
sample of the reference book (source pages 1, 19, 20, 21 and 22), using MinerU
online recognition and the configured DeepSeek provider (`deepseek-v4-pro`) for
translation. No other live call was made.

**Result: PASS for the exercised path.**

- The job was created through the real Web API (`/api/upload` then
  `/api/translate` with per-task PDF consent), polled through
  `/api/translation/<id>`, and the finished PDF was downloaded through
  `/api/files/<name>`.
- Recognition: 5/5 pages, 65/65 recognised blocks accounted for, 14 justified
  exclusions, 10 image instances, `coverage.complete: true`.
- Translation: 17/17 chunks, 0 failed, 88.1 s end to end (recognition plus 17
  translation calls). Output: 8-page reflowed PDF, 5,579 characters, 4,618 CJK
  characters, 10 images.
- Output metadata: title `STADTPLANUNG`, empty author, no preview notice and no
  preview suffix. The accounting sidecar records `whole_book_coverage: true`,
  `recognition_accuracy_proven: false`, `every_visible_word_translated: false`.
- Private evidence stayed under Git-ignored `data/live-acceptance/` (PDF, page
  renders, summaries); only this redacted summary is published.

Environment notes:

- The local VPN runs fake-IP DNS and returned an unreachable `198.18.x` address
  for the MinerU result CDN. The live server was started with a process-local DNS
  override (DoH to 1.1.1.1 for that host only); no application code or security
  behavior changed.
- Earlier attempts failed with `[Errno 22]` because several orphaned server
  processes from killed background jobs were racing on the same port. After
  killing them and running one server, the run completed.

Not observed live: a pause at the five-minute local budget and its continuation
(the sample finished in 88 s). The saved-task continuation after a failed result
download is recorded in the private evidence, but it is not the 5-minute-pause
scenario.

### Twenty-page acceptance run (operator bar)

The operator then set the acceptance bar at a twenty-page live run. The first
attempt failed closed at result validation with `mineru_result_invalid`: the
online V2 result contained `page_footer` blocks (two instances) that the loader
did not recognise. The loader and adapter were extended to treat typed page
footers as running matter in the bottom margin, with an explicit exclusion
reason, and to retain a footer outside that band with a review finding
(`77eb24c`, three new tests). Unknown types remain fail-closed.

The same job then continued from its saved recognition result (no re-upload and
no resubmission) and completed:

- Recognition: 20/20 pages, 230/230 recognised blocks accounted for, 0
  unaccounted, 36 justified exclusions (including the two page footers), 29
  image instances, `coverage.complete: true`.
- Translation: 59/59 chunks, 0 failed; 230.8 s for the resumed translation run.
  Output: 23-page reflowed PDF, 19,859 characters, 16,522 CJK characters, 29
  images.
- Metadata: title `STADTPLANUNG`, empty author, no preview notice or suffix; the
  accounting sidecar reports complete coverage with the same honest limitations
  (`recognition_accuracy_proven: false`, `every_visible_word_translated: false`).
- The two page footers are excluded as running matter and do not appear as body
  text.

**Result: PASS after the fix.**

## Acceptance record

- **2026-10-17:** the operator accepted the twenty-page live run as release
  acceptance. The bar was explicitly set at twenty pages; a 198-page reference
  run was not requested.
- **Exercised live:** Web upload with per-task consent, MinerU online
  recognition, result validation, DeepSeek translation, PDF generation and
  validation, download, and accounting. The twenty-page run included a real
  contract fix (`page_footer`, `77eb24c`) and continued from the saved
  recognition result without re-upload or resubmission.
- **Not exercised, waived by the operator for this personal-use release:** live
  five-minute pause and continuation, runtime browser smoke, and independent
  human visual review. Static and server-side UI checks and the focused tests
  pass, but no live browser session was run.
- **Still true:** automated accounting is not proof of recognition accuracy or
  translation quality; the live output remains a private personal-use artifact.
- Private artifacts stay under Git-ignored storage; only redacted summaries are
  published.

## Redaction and data handling

No credential, token, signed URL, provider payload, or private document content
is included in this report. The synthetic PDFs, synthetic MinerU V2 archives,
temporary SQLite stores, and temporary output directories used by the tests were
generated locally. The read-only risk checks wrote only under the operating
system's temporary directory and were not committed.
