# Fiction Quality: Development Inventory (2026-10-19)

## Decision

The quality workflow has substantial local implementation, but is not shipped
on remote `main` and has not demonstrated a literary-quality improvement.
Prioritize usable candidate translations and verified output correspondence
before another blind assessment. Do not restart implementation from the open
issue list or treat engineering tests as human acceptance.

## Snapshot and boundaries

- GitHub parent #1 and T01-T12 (#2-#13) are all open. No open PR was observed.
- Remote `main` is `0339be8`, the merged MinerU release. Its tree has none of
  the quality/fiction implementation paths inventoried here.
- The primary `TranslateBooksWithLLMs` worktree is on local `main` at
  `bd6df440253ecf4a0aee482002bdc4402b59f1d4`, one commit ahead and forty
  behind `origin/main`. That unique commit adds the initial quality workflow
  across 56 files; it is not part of the MinerU merge.
- The same worktree has additional tracked modifications and untracked
  evaluation, E2E, graph, and documentation files. This inventory reads the
  committed implementation plus that working tree. Neither has been reset,
  rebased, merged, staged, or committed by this task.
- This report and the MinerU documentation sync live separately on
  `codex/sync-mineru-quality-status`, based on `origin/main`, in the
  `TranslateBooksWithLLMs-mineru-online` worktree.
- File paths in the table below refer to the primary quality worktree, not
  to implementation available on this report's branch. Existing progress and
  review documents there contain historical evidence, not a new acceptance.

## Ticket inventory

**Subsequent operator decision:** the local quality line described above has
now been archived without merging it. The snapshot facts above describe the
pre-archive working tree. Local `main` now contains the MinerU release; recovery
references and the exact preservation procedure are recorded in
[the archive record](quality-archive-2026-10-19.md). No quality acceptance or
issue state was changed by this archival operation.

Every row remains OPEN on GitHub. "Present" means implementation and focused
test evidence were found; it does not mean every ticket criterion was audited.

| Ticket | Local implementation/evidence | Current qualification |
| --- | --- | --- |
| T01 / #2 | `benchmark/fiction.py`; `test_fiction_corpus.py` | Inventory, frozen selection, reversible TXT derivation, and source/reference isolation are present. Local progress records nine private cases; private corpus alignment was not re-inspected in this inventory. |
| T02 / #3 | `src/core/quality/options.py`, `workflow.py`; `test_quality_txt_translation.py` | Opt-in English-to-Simplified-Chinese TXT review is present; unsupported format/direction/refinement combinations are rejected. |
| T03 / #4 | `workflow.py`; `test_quality_workflow.py` | Source-grounded findings, invalid-assessment handling, and two persistent repair rounds are present. Invalid review does not become success. |
| T04 / #5 | `QualityWorkflow.prepare`, plain-text pipeline integration | Full-source preparation and frozen source plans feed drafting; preparation/projection ordering has focused tests. |
| T05 / #6 | `QualityWorkflow.context_for`, `prompt_context` | Prior-source facts/summaries and applied accepted examples are bounded; failed projections cannot become reliable examples. |
| T06 / #7 | `src/persistence/database.py`, checkpoint integration | Additive state, optimistic revisions, replay, and non-resetting repair reservations are present. Restart, source mismatch, stale-writer, and projection-barrier tests pass. |
| T07 / #8 | `src/core/quality/epub.py`, native XHTML/EPUB owners | Structured EPUB integration and packaging tests are present. Source locators and native format validation remain important during integration. |
| T08 / #9 | Native plain-text EPUB bridge | The same shared quality owner supports plain-text EPUB; its parameterized public-entry test passes. |
| T09 / #10 | `QualityWorkflow.audit` | Neighbor/term audit, shared repair allowance, and native output re-application are present and tested. |
| T10 / #11 | API quality report, `quality-status.js`, seven locales | Report/status/UI implementation exists. Local reports record browser and authenticated E2E proof; those live/browser checks were not repeated here. |
| T11 / #12 | `fiction_run.py`, `fiction_comparison.py`, untracked `fiction_judge.py` | Isolated execution, receipts, resume identity, explicit output spans, anonymous judgments, and rejected-assessment handling exist. The real-corpus comparison is blocked by candidate readiness and correspondence. |
| T12 / #13 | Human acceptance process and pending judgments | NOT ACCEPTED. Earlier AI quality inference and the claim of eight human-ready pairs were explicitly withdrawn. |

## Real-corpus evidence and actual blocker

The primary worktree's current `docs/reports/fiction-quality-ai-pre-review.md`
withdraws the earlier comparison. It records refusal/English-only material in
candidate passages and unsafe automatic positional pairing. Its progress
document records two exported partial drafts, each with one nominal untranslated
chunk, and a quality outcome of `review_required`. These are report-derived
facts; no private book or provider receipt was opened for this inventory.

The earlier `fiction-quality-ai-pre-review-blocked.md` describes a prior attempt
where preparation failed. It must not be treated as the latest run state.
Likewise, the initial review's "T01-T11 available" statement describes an
engineering surface, not a valid real-novel comparison or a shipped feature.

Current code removes automatic EPUB positional matching: both TXT and EPUB
require explicit output spans, and the AI judge rejects legacy sheets without
`pairing_method=explicit_output_spans`. However, `build_comparison` marks a case
aligned when both supplied spans yield text, and the judge checks the sheet's
alignment declaration. These checks do not establish that the text is a usable,
faithful translation. The guide requires substantive candidate inspection;
the current human packet remains blocked according to the withdrawal report.

## Current proof

With `PYTHON_DOTENV_DISABLED=1` and the configured project interpreter, the
following focused suite ran against the primary quality working tree:

```powershell
python -m pytest tests/unit/test_quality_workflow.py `
  tests/unit/test_quality_txt_translation.py tests/unit/test_quality_epub_translation.py `
  tests/unit/test_fiction_corpus.py tests/unit/test_fiction_comparison.py `
  tests/unit/test_fiction_run.py tests/unit/test_fiction_relay.py `
  tests/unit/test_fiction_judge.py -q
```

Result: **51 passed**, one existing invalid-escape SyntaxWarning, 7.11 seconds.
No credentials were read and no provider requests were made. This was not a full
regression, browser smoke, real-book comparison, or independent human review.
Historical broad results in the local progress document retain their explicit
legacy/Ollama/E2E exclusions and were not rerun here.

## CRG setup and verification

The primary worktree's existing graph was rebuilt through its locked
`scripts/graph_health.py --rebuild` entry point. The online worktree's missing
graph was initialized after copying the existing graph-ignore policy. Final
stored statistics, after post-processing, are:

| Worktree | Indexed files | Nodes | Edges | Languages |
| --- | ---: | ---: | ---: | --- |
| Primary quality worktree | 511 | 7,178 | 55,682 | bash, JavaScript, Python |
| Online documentation worktree | 538 | 7,789 | 62,533 | bash, JavaScript, Python |

Both graphs match their worktree HEAD and have no indexed private, dependency,
or foreign paths in the scope check. Builds reported no parse errors; existing
invalid-escape SyntaxWarnings remain. The primary health check passes. The
current index does not contain untracked `benchmark/fiction_judge.py`; its
behavior was inspected directly and tested, so graph coverage is not treated
as complete. No embeddings or external model calls were enabled.

## Recommended sequence

1. Preserve the dirty quality worktree and private artifacts. Before integration,
   capture a reviewable quality snapshot on a separate branch without resetting
   local `main`; include the currently untracked tooling needed by the tests.
2. Reconcile #2-#12 against that exact snapshot, attaching per-ticket proof and
   remaining qualifications. Do not close them solely from this inventory.
3. Inspect actual candidate passages and confirm source/target correspondence.
   Explicit spans must not turn refusal or untranslated material into a ready
   comparison. Keep all frozen cases and missing/invalid cases visible.
4. If usable drafts require regeneration, define a controlled, separately
   authorized run; preserve frozen identity, accepted preparation, and consumed
   repair allowance. Then produce a new blind packet and independent human
   judgments for #13. Do not reuse withdrawn AI scores.
5. Integrate quality work into current `origin/main` in an isolated branch and
   prove both quality behavior and MinerU regressions. The two lines share
   changes in dispatch, plain-text checkpoints/pipeline, API handlers/routes,
   job persistence, Web tracking/templates, and repository checks. A blind
   cherry-pick or merge is not evidence of compatibility.

The present task synchronizes local documents and inventories evidence. It does
not authorize a new paid run, change issue states, or publish the local branch.
