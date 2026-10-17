# Issue Tracker: GitHub

Issues and specs live in GitHub Issues for
`rookie2onion/TranslateBooksWithLLMs`. Use the `gh` CLI.
Explicitly pass `--repo rookie2onion/TranslateBooksWithLLMs`
to issue and pull-request commands.

## Operations

- Create: `gh issue create --repo rookie2onion/TranslateBooksWithLLMs --title "..." --body-file -`
  Supply multiline bodies through a heredoc.
- Read: `gh issue view <number> --repo rookie2onion/TranslateBooksWithLLMs --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --repo rookie2onion/TranslateBooksWithLLMs --body "..."` (or `--body-file -`)
- Label: `gh issue edit <number> --repo rookie2onion/TranslateBooksWithLLMs --add-label <label>`
- Claim: `gh issue edit <number> --repo rookie2onion/TranslateBooksWithLLMs --add-assignee "@me"`
  Quote `@me` in PowerShell so it is not parsed as a splat token.
- Close: `gh issue close <number> --repo rookie2onion/TranslateBooksWithLLMs --comment "..."`

When a skill says "publish to the issue tracker", create a GitHub issue.

## Parent Issues and Blocking Dependencies

Use native GitHub sub-issues to connect tickets to a parent spec or map.
If unavailable, add `Part of #<parent>` to each child and a task list
to the parent.

Use native issue dependencies for blocking edges:

`gh api --method POST repos/rookie2onion/TranslateBooksWithLLMs/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`

Get the blocker's database ID with:

`gh api repos/rookie2onion/TranslateBooksWithLLMs/issues/<blocker> --jq .id`

The database ID is not the issue number or node ID.
If dependencies are unavailable, record `Blocked by: #<number>`
at the top of the child issue. Work blockers first.

## Wayfinder Maps

A map is a parent issue containing the destination, constraints,
open frontier, linked child tickets, and decisions so far.

Child tickets use `wayfinder:<type>` labels:
`research`, `prototype`, `grilling`, or `task`.

Resolve a ticket by commenting with the answer, closing it,
and adding a concise decision with a source link to the map.

## Pull Requests as a Triage Surface

**PRs as a request surface: no.**

GitHub issues and pull requests share a number space.
If an ambiguous reference cannot be read as an issue, check it
with `gh pr view`.
