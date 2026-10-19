# Quality Optimization Archive and MinerU Main Adoption

Date: 2026-10-19. The operator requested archival without merging the
optimization line, adoption of MinerU on main, and a server for manual
198-page acceptance. No branch named performance/optimization existed;
the optimization line was identified from the preceding quality inventory.

## Preserved local state

- Original committed quality tip: `bd6df440253ecf4a0aee482002bdc4402b59f1d4`.
- Archive branch: `codex/archive-quality-2026-10-19`, created by renaming the
  former local `main`; the unique quality commit was not merged.
- Working state: an include-untracked stash, pinned independently by local
  tag `archive/quality-working-state-2026-10-19` at
  `f86155c` (a stash commit, not a release commit).
- Exact-byte backup: ignored
  `data/dev-archives/quality-2026-10-19/working-tree.zip`, with `manifest.json`
  recording SHA-256 values for all 38 modified/untracked files. ZIP integrity
  and every archived file hash were checked before stashing.
- Ignored environments, private corpora/settings, and generated artifacts were
  retained on disk. Private `*.env` profiles remain excluded locally after
  switching to the release tree. No archive ref or private backup was pushed.
- `data/jobs.db` was copied to
  `data/dev-archives/quality-2026-10-19/jobs-before-manual-test.db` before
  launching the release server. This is a local pre-start backup, not a new
  format migration or a substitute for the private corpus.

## Main branch

New local `main` was created from `origin/main` at
`0339be8b18c0598f94c5ad8e3aafee4ba7fd449a`. A fast-forward-only merge check
of `feat/mineru-online-translation` returned "Already up to date": PR #25
already includes it. The archived quality tip is not an ancestor of this main.
The documentation follow-up may advance local main, without incorporating
quality implementation. Original quality issues remain open.

## Recovery in a separate checkout

Keep the main checkout available for MinerU. To recover the archive, choose an
unused destination and use the saved branch plus the pinned working state:

```powershell
git worktree add ../TranslateBooksWithLLMs-quality-restore codex/archive-quality-2026-10-19
git -C ../TranslateBooksWithLLMs-quality-restore stash apply archive/quality-working-state-2026-10-19
```

The ZIP is an additional byte-preserving backup. Its manifest can be used to
check restoration; Git may normalize line endings. Private ignored datasets,
settings, and virtual environments remain in their original locations and
are not automatically copied by `git worktree add`.

## Manual 198-page test

The release server uses the primary main checkout, the existing online Python
environment, native DeepSeek `deepseek-v4-pro`, and the existing MinerU dotenv
configuration. It binds to `http://127.0.0.1:5000/`. The previous process-local
MinerU CDN DNS shim is reused for the local fake-IP environment; no application
network validation or TLS verification is disabled.

The private launcher/logs are under `data/manual-acceptance/`. Starting the
server does not submit the book. The operator selects the source PDF and grants
per-task authorization in the browser. A paused recognition task must use
Continue, preserving its remote identity, rather than a replacement submission.
The 198-page run has not been declared complete by this setup record.

See [the over-200-page research](mineru-over-200-pages-research.md) for larger
documents. That report recommends manual physical splitting today and records
what a future automatic book-level workflow would need to preserve.
