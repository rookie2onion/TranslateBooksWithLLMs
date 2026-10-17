# MinerU online service-contract research

Researched: **2026-10-17 UTC** (runtime clock). Public documentation only; statements describe retrieved documentation, not exercised vendor behavior. No implementation or product decisions.

## Primary sources

- **[A] Current API documentation:** https://mineru.net/apiManage/docs — sections “Mode comparison,” precise parsing, task results, batch upload, common errors, and lightweight Agent API.
- **[P] Footer-linked privacy policy:** https://webpub.shlab.tech/dps/opendatalab-web/odl_v5.1690/privacy.html — OpenDataLab policy, header updated August 16, 2022; sections V and VIII.
- **[T] Footer-linked service agreement:** https://webpub.shlab.tech/dps/opendatalab-web/odl_v5.1690/service.html — OpenDataLab agreement, updated August 17, 2022; sections 2.1, 2.4, 3.2, 5.4. Footer destinations were recovered from the documentation page's public localization asset.

- **[L] Local reference-file check:** the source file matches the SHA-256 recorded in the private probe metadata, which records 198 source pages. Its measured size is 50,634,055 bytes. This local inspection made no provider request and does not authorize an upload.

## Verified statements and unknowns

| Topic | Evidence / qualification |
|---|---|
| Standard API per file | **Verified [A]: at most 200 pages and 200 MB.** Exact byte interpretation of “MB” is unspecified. The fingerprint-matched 198-page reference PDF is 50,634,055 bytes [L], within both documented limits; actual submission remains subject to authorization and service validation. A probe's five-page selection is not a provider limit. |
| Batch / concurrency | **Conflicting [A]:** comparison says up to 200 files; both detailed local-upload and URL-batch instructions say at most 50 links per request. Effective batch maximum needs clarification. Numeric concurrent-task/request-rate limits are unverified. |
| Account / quota / price | **Verified [A]:** standard API requires an account-created token; 1,000 pages/account/day receive highest priority, with lower priority beyond that—not a stated hard page cap. Error `-60018` indicates a separate daily task cap, without its number. Current hosted API price, paid tiers and account-specific allowances are unverified. [T] 2.1 calls its data platform free, not a current MinerU API price guarantee. |
| Polling / errors | **Verified [A]:** asynchronous submission returns task/batch identifiers; API success uses `code=0`. Standard result states include `pending`, `running`, `converting`, `done`, `failed`; batch results additionally include `waiting-file`. Failed tasks carry `err_msg`; running tasks expose page progress. Successful submission is not successful recognition. |
| Timeouts / retry | **Verified [A]:** upload URLs last 24 hours. Error `-60008` means file-read timeout, `-60009` queue full, `-60017` retry limit reached; no numeric remote execution deadline or retry allowance is specified. “Retry later” is guidance, not an idempotency guarantee. No documented submission deduplication/idempotency contract found; `data_id` is business correlation. Callback HTTP 200 acknowledges delivery; failures trigger up to five repeat notifications. The lightweight example's 300-second polling timeout is client code, not a remote deadline. |
| Cancellation / deletion | **Partial [A]:** `-60014` explicitly says running tasks cannot currently be deleted; `-60012` references missing/deleted tasks. No callable cancellation/deletion endpoint or comprehensive lifecycle contract found. Stopping local polling does not establish remote cancellation. |
| Retention / privacy | **Unknown:** no verified result-download-link lifetime or submitted-document/result deletion schedule found in [A]. Upload-link expiry is neither output-link expiry nor document deletion. [P] covers personal information: purpose-limited retention, later deletion/anonymization, deletion-request replies within 15 working days, and delayed backup removal. These are not a document-specific purge deadline or completion guarantee. |

## Interview implications and unresolved questions

Clarify byte units, batch conflict, concurrency, daily task caps, retry costs and duplicate-submission behavior. Confirm output-link lifetime, source/result/cache/backup retention, training reuse, deletion mechanism and cancellation eligibility. Determine applicability of the older linked policies: [T] restricts commercial use and account sharing without permission; API access can be suspended for excessive requests. Seek current integration/commercial terms rather than infer permission.

Lightweight Agent parsing is a different service: [A] specifies 10 MB/20 pages and IP throttling (HTTP 429), but a failure example says 50 pages. It cannot establish whole-book eligibility. No login, credentials, recognition calls, uploads or whole-book E2E tests occurred.
