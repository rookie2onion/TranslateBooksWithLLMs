# Translating PDFs longer than 200 pages with MinerU

Researched: **2026-10-19, Asia/Hong_Kong**. Public primary documentation and local integration source only. No recognition requests, credentials, private-book inspection, or implementation changes were involved.

## Recommendation

Keep the existing 200-page admission limit. For an occasional longer book, physically split the source locally into non-overlapping chapter-aligned PDF volumes, translate each as its own existing task, and retain the separate outputs and accounting reports. Start with approximately **100–150 pages per volume**, smaller for image-heavy scans or the Web upload ceiling. This is an operational judgment, not a MinerU limit or a promise to finish within five minutes. A 198-page PDF is already within the current page gate; it does not need splitting merely because it is close to 200.

Do not claim an automatic whole-book workflow exists. A proper future implementation should add book-level orchestration above the current single-document recognition workflow and preserve that workflow's identity, validation, and no-resubmission guarantees.

## Hosted service facts and documentation conflicts

The following is documentation evidence, not account-specific eligibility or observed provider behavior.

| Topic | Verified public documentation / remaining uncertainty |
|---|---|
| Current standard service | Current [API management documentation](https://mineru.net/apiManage/docs) specifies **200 pages / 200 MB per file**, with **1,000 highest-priority pages per account per day**; later pages have lower priority. The MB byte interpretation and numeric daily task cap are unspecified. |
| Batch | The same [current documentation](https://mineru.net/apiManage/docs) conflicts internally: comparison allows 200 files; detailed upload and URL-batch instructions allow 50. Neither expands the per-file ceiling. Numeric concurrency is unspecified. |
| Page selection | [Current documentation](https://mineru.net/apiManage/docs) defines `page_ranges` / `file.page_ranges` as page selection, including `2,4-6`. It does **not** promise that selecting fewer pages bypasses the source-file limit. Error `-60006` recommends splitting. |
| Priority and price | Priority allowance is not a stated hard daily page cap. Current price, purchasable higher limits, and account-specific entitlement are unverified. Upload URLs expire after 24 hours; this does not establish result retention. See [current documentation](https://mineru.net/apiManage/docs). |
| Conflicting older documentation | The separately served [Chinese reference](https://mineru.net/doc/docs/) and [English reference](https://mineru.net/doc/docs/index_en/) still state 600 pages and 2,000 highest-priority pages/day. The [index_pro page](https://mineru.net/doc/docs/index_pro/) also states those figures and an additional user token header. These conflict with the current management page and do not establish a supported paid upgrade for this account. |

**Decision:** use the conservative 200-page contract already enforced by this application. Resolve any proposed larger hosted limit with the provider and an explicitly authorized contract test before changing admission, validation, errors, or UI. The `index_pro` filename alone is not evidence that buying a plan raises this project's limit.

**Unknown:** whether a >200-page original with `page_ranges="1-150"` is accepted, how returned page indices behave for sparse selections, exact billing of selected pages, effective batch maximum, and current paid quota options. None was probed. Physical splitting avoids depending on the first two unknowns.

## What this integration currently owns

These statements are verified against the local source; paths are repository-relative.

- [`src/core/mineru/admission.py`](../../src/core/mineru/admission.py) checks task authorization, token availability, unencrypted/readable PDF, byte count, and actual page count before any submission. Its limits are 200 pages, 200,000,000 bytes and a **300-second local recognition budget**. [`src/utils/security.py`](../../src/utils/security.py) keeps the general Web upload ceiling at **100 MiB (104,857,600 bytes)**, so that lower ceiling governs ordinary Web uploads. The provider's advertised 200 MB is not the Web limit.
- [`src/core/mineru/client.py`](../../src/core/mineru/client.py) uses `/api/v4/file-urls/batch` with exactly **one file**, `vlm`, OCR, tables and formulas enabled. It does not send `page_ranges` and expects exactly one upload URL. Provider batch availability is not an existing application multi-file implementation.
- [`src/core/mineru/recognition.py`](../../src/core/mineru/recognition.py) and [`recognition_state.py`](../../src/core/mineru/recognition_state.py) durably bind remote work to the task and source fingerprint. Continue gives the same known remote task another bounded polling/download attempt; it does not upload or submit again. `submitting` / `submission_unknown` remain blocked from automatic resubmission because the provider may already have received the request. An incomplete upload cannot be replayed automatically because its one-time signed destination is deliberately not persisted.
- [`src/core/mineru/result.py`](../../src/core/mineru/result.py) writes and verifies an exact `1..N` source-page manifest for the admitted PDF and still checks the 200-page ceiling. Raising only the admission constant or adding `page_ranges` would not produce correct partial-document accounting.
- [`src/core/mineru/cache.py`](../../src/core/mineru/cache.py) already distinguishes zero-based local `sample_index` from one-based `source_page`; [`structure.py`](../../src/core/mineru/structure.py) carries this into provenance, figures and source-preserved tables/formulas. This is the fitting mapping layer to extend, rather than rewriting raw provider page indices.
- [`src/core/pdf/accounting.py`](../../src/core/pdf/accounting.py) requires exact source coverage, complete block accounting and completed translation chunks before whole-book completion. Retained figure pixels and source-preserved table/formula images remain untranslated. Coverage is not OCR accuracy, visual correctness, or proof that every visible word is translated.

The 300 seconds apply to one recognition execution, including its transfer, polling, waits and retries. They are neither a remote job deadline nor the complete translation time. A large document may require Continue while its remote recognition keeps running. Do not start a replacement task merely because the local budget expired.

## Manual workflow available now

1. Keep the original unchanged. Record its SHA-256, physical PDF page count and an ordered volume manifest outside published content. Use physical PDF pages, not printed Roman/Arabic page labels.
2. Split by whole pages locally with an existing trusted PDF tool. Prefer chapter boundaries near 100–150 pages. Ensure every volume is at most 200 pages and **below 100 MiB** for the current Web route; measure the resulting file rather than estimate from the original's average size. Split an oversized volume again. Preserve page content and rotation instead of rasterizing the entire book.
3. Name volumes unambiguously, for example `book-v01-p0001-0120.pdf` and `book-v02-p0121-0240.pdf`. Record source range, extracted-file hash and page count. Require ordered ranges to be disjoint and to cover every original page once. No overlapping recognition pages by default.
4. Use the same target language, provider/model, custom instructions, glossary and terminology decisions for all volumes. Translate serially so reviewed terminology can be carried forward deliberately. Save the exact glossary/settings version used per volume; otherwise editing a shared glossary halfway through makes the result inconsistent and unauditable. Inspect sentences, footnotes and tables that cross a split boundary.
5. Create and authorize one existing translation task per volume. Keep its task ID. For a recognition timeout use its existing Continue action, then download the translated PDF and both available reports. Do not reupload to restart known remote recognition. Distinguish source-preserved material from translated text in manual acceptance.
6. Treat each task's report as complete **for that extracted file only**. Its page 1 corresponds to the manifest's original start page. Keep the volume manifest beside all outputs; do not edit a report's source fingerprint to pretend it came from the original book.
7. Keeping separate translated volumes is the simplest truthful delivery today. If one reading PDF is needed, concatenate only accepted PDFs in manifest order, create a new composite identity, and retain child reports and the mapping manifest. Reflowed translated output page counts will differ from source counts, so output-page arithmetic cannot prove source coverage. A merge can also lose bookmarks, internal links, metadata and report-to-output identity; review those separately. Do not present a child report as validation of the merged PDF.

This workflow is a recommendation only; no book was split or uploaded by this research task.

## Smallest coherent future automatic workflow

Add a book plan at the existing task/workspace orchestration boundary. Keep the current recognition client, state machine and single-volume validator as children; do not introduce a second provider retry loop.

| Responsibility | Required invariant |
|---|---|
| Book manifest / splitter | Immutable original hash, byte count and page count; ordered volume IDs and hashes; explicit original page list per volume; no gaps or duplicates; every child satisfies both Web/local and provider limits. Splitting is local before remote admission. |
| Authorization | One clear authorization may cover the displayed whole-book plan, but each child must be bound to that authorized original and plan. An altered source or plan cannot silently reuse it. Never manufacture consent inside the network client. |
| Child recognition | Persist child record before submit; maintain its own source identity, batch ID and phase. Resume validated children locally and known remote children by polling. Unknown submission outcomes remain blocked. Start with serial recognition to avoid undocumented concurrency and quota assumptions. |
| Page mapping | Preserve local provider indices. Map `global_source_page = original_start_page + local_page_index` for contiguous volumes, or use an explicit page-list lookup. Map at cache/structural adaptation, before building provenance and accounting. Key blocks/assets with volume identity so local index 0 in two volumes cannot collide. |
| Translation consistency | Freeze common glossary and translation settings at book level. Keep translation checkpoints per child. A deliberate glossary revision must mark affected children stale or create a new version; silently mixing versions is unacceptable. Boundary context can be supplied as context-only text, without duplicating it as translated content or counted coverage. |
| Composition | Concatenate canonical content in manifest order and render once where practical, reusing the existing renderer. Rebase paragraph/output anchors, figure captions and footnotes with stable child-to-global IDs. Preserve image/formula/table bytes, labels and provenance. Do not merely concatenate raw JSON arrays or infer completeness from PDF page count. |
| Aggregate accounting | Verify union of global source pages equals `1..N`, multiplicity is exactly one, child identity/report hashes match, every recognized block is accounted for, all required translation chunks are complete, and settings versions agree. Include child reports, source-preserved counts, exclusions, unknown types and boundary-review findings. Partial children yield a partial book. |
| Resume and publication | Persist plan and child progress atomically; serialize work on the same book/child so Continue cannot double-submit. Keep the 300-second child attempt budget and honest paused state. Render/publish only after aggregation passes; interrupted composition must retain accepted children and be safely repeatable. |

**Minimum future proof:** offline fixtures for a 201-page source split across two children; gap/overlap rejection; local/global page and asset-anchor mapping; different source/settings refusal; one child timing out then continuing without a second submit; unknown submission blocked; partial-child aggregation refused; and source-preserved figures/formulas visible in the final composition. Use small synthetic page fixtures rather than a private whole-book API call for these invariants.

## Alternatives and decision boundary

- **Higher hosted tier:** current price and greater page entitlement are unverified. Ask the provider to confirm the exact endpoint, account entitlement, billing, retention, batch/concurrency, selected-page semantics and output contract. Keep this separate from the present standard integration. The conflicting [index_pro reference](https://mineru.net/doc/docs/index_pro/) is insufficient for a production change.
- **Self-hosted MinerU:** the official [V1 HTTP API documentation](https://opendatalab.github.io/MinerU/usage/http_api/) documents local deployment, asynchronous tasks and explicit per-file/task limits. It also warns that job/resource indices are in memory and do not survive service restart. Its `/v1` interface and result lifecycle differ from this application's hosted `/api/v4` contract. Self-hosting can put resource and data-location decisions under operator control, but requires a separately verified adapter, output-schema compatibility and durable orchestration. It is not achieved by changing the base URL. Check deployment hardware, models and current licensing before selecting it.
- **Agent lightweight endpoint:** the [current hosted documentation](https://mineru.net/apiManage/docs) limits it to 20 pages/10 MB and Markdown output. It does not fit this whole-book structured reconstruction contract.

Finish and inspect the 198-page manual test first. It will give useful evidence about recognition pauses, reconstruction size, unknown content types and translation quality before deciding whether automatic multi-volume orchestration is worth implementing.
