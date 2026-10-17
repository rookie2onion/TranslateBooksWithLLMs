# Domain Docs

## Layout

This repository uses a single-context layout:

- `GLOSSARY.md` at the repository root.
- Architecture Decision Records under `docs/adr/`.

The root glossary and ADR directory record confirmed terminology
and architectural decisions. Extend them as decisions are resolved;
do not invent definitions or decisions to fill the layout.

## Read Before Exploration

Read `GLOSSARY.md` when present.
Read ADRs relevant to the area being explored or changed.

## Use Domain Vocabulary

Use glossary terms consistently in issues, designs, hypotheses,
tests, and code. Avoid synonyms the glossary explicitly rejects.

If a required concept is missing, reconsider whether it belongs
to the domain, or flag the gap for `/domain-modeling`.

## Surface Decision Conflicts

If a proposal contradicts an ADR, identify that ADR explicitly
and explain why the decision should be reconsidered.
Do not silently override recorded decisions.
