# Agent & Contributor Guidelines

Instructions for anyone — human or AI assistant — contributing to this repository.

## Commit & PR attribution policy

**Do not add AI/assistant attribution to commits, pull requests, or history.**

Specifically:

- **Never** add a `Co-Authored-By:` trailer for an AI tool — e.g. `Co-Authored-By: Claude <...>` or any `@anthropic.com` / assistant address.
- **Never** add "Generated with …", "Co-authored by an AI", or similar footers to commit messages or PR descriptions.
- This applies to **every contributor and every tool**. No trace of the assistant should appear in the pushed history.

> This overrides the generic "commits … with co-author trailer" guidance in `CONTRIBUTING.md`: that trailer is for **human** co-authors only, never for AI tools.

If you use an AI assistant while working, that's fine — just author the commit as yourself, with no assistant attribution anywhere in the message, trailer, or PR body.

## Local-first workflow

- Do local work freely (edits, local branches, local history rewrites, builds, tests).
- **Do not commit, push, force-push, or take any remote/production-affecting action without explicit maintainer approval.**

## See also

- `CONTRIBUTING.md` — full contribution process (conventional commits, signing, CI gates, ADRs).
