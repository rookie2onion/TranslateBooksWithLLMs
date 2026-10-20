# Printed contents in local MinerU EPUB exports

## Accepted behavior

The user accepted the text-only contents prototype and requested production integration. The ordinary local command now restores a conservatively recognized printed contents region as text lists and links. It automatically identifies the named contents page and admits continuation pages only with contents-shaped records and at least two matches in later body content. No page-range option, recognition pass, model, or dependency is added.

```powershell
python -m src.core.mineru --input "D:\Books\mineru-result" `
  --output-dir "D:\Books\original-epub" --language de --title "Book title"
```

## Ownership and invariants

- `printed_toc.py` consumes admitted raw layout records before line/span information is flattened. It retains source block identity, span/range evidence, literal printed labels and target evidence. Mixed-title search is bounded; incomplete or ambiguous recovery remains visible source text.
- The local loader attaches the plan to its cache. Only `build_original_epub` requests contents-aware adaptation. Translation/PDF and cached preview adaptation keep their existing behavior.
- `structure.py` emits contents entries as normal text rather than duplicate body headings. Caption-free contents images receive explicit exclusions; substantive captions and other image placements are retained. Every source block remains accounted for.
- The existing EPUB renderer owns list markup, paragraph anchors and final link resolution. Targets are resolved after final paragraph indices and section filenames exist. Missing rendered targets remain unlinked rather than generating dangling fragments.
- Matching prefers a unique exact heading, a unique spacing-normalized heading, then a unique exact paragraph. Wording variants require a recognized matching printed page label and ordered substantive title words. A repeated running header on one contiguous page run can locate a missing section heading's first content block. Printed numbers are never treated as EPUB pagination or a fixed PDF offset.
- The report includes the admitted pages, recovery methods, source evidence, intentional image omissions and per-entry targets. Existing table/formula preservation and input/output validation remain in force.

## Acceptance

The accepted Stadtplanung prototype's two physical contents pages contain 75 entries. The production command must reproduce 75 resolvable links, no contents images, complete recognized text coverage, and zero unaccounted source blocks. Body text, ordered figures and image bytes must match the accepted rendition; only output anchor identifiers may change. Normal and narrow EPUB reflow must remain readable.

Focused command-boundary regressions cover mixed source fragments, positioned columns, wrapped titles, spacing variants, exact paragraph anchors, page-backed wording differences, running-header section starts, duplicate targets, unknown text retention and continuation-page rejection. Existing local export and cached-preview suites remain required.

The other supplied legal handout remains a conversion regression sample. Documents without a proven contents region use the ordinary export path. This is not a promise to recover arbitrary contents tables, missing words or source typography.

The disposable demo stays on `codex/prototype-mineru-toc-validation`, last accepted commit `b389f25`. Its code and HTML shell are not dependencies of production and are not merged into main. The accepted decisions are captured here.
