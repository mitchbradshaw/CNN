---
name: setup-matt-pocock-skills
description: Configure this repo for the engineering skills — set up its issue tracker, triage label vocabulary, and domain doc layout. Run once before first use of the other engineering skills.
disable-model-invocation: true
---

# Setup Matt Pocock's Skills

Scaffold the per-repo configuration that the engineering skills assume:

- **Issue tracker** — where issues live (GitHub by default; local markdown is also supported out of the box)
- **Triage labels** — the strings used for the five canonical triage roles
- **Domain docs** — where `CONTEXT.md` and ADRs live, and the consumer rules for reading them

This is a prompt-driven skill, not a deterministic script. Explore, present what you found, confirm with the user, then write.

## Process

### 1. Explore

Look at the current repo to understand its starting state. Read whatever exists; don't assume:

- `git remote -v` and `.git/config` — is this a GitHub repo? Which one?
- `AGENTS.md` and `CLAUDE.md` at the repo root — does either exist? Is there already an `## Agent skills` section in either?
- `CONTEXT.md` and `CONTEXT-MAP.md` at the repo root
- `docs/adr/` and any `src/*/docs/adr/` directories
- `docs/agents/` — does this skill's prior output already exist?
- `.scratch/` — sign that a local-markdown issue tracker convention is already in use
- Is the `triage` skill installed? This decides whether the triage-labels section runs at all.
- Monorepo signals — a `pnpm-workspace.yaml`, a `workspaces` field in `package.json`, or a populated `packages/*` with its own `src/`.

### 2. Present findings and ask

Summarise what's present and what's missing. Take the decisions in order — issue tracker, then triage labels (only if the `triage` skill is installed), then domain-doc layout (single `CONTEXT.md` by default; multi-context only if monorepo signals were found). Lead each with a recommended answer so the user can accept it in a word.

### 3. Confirm and write

Show the user a draft of the `## Agent skills` block to add to whichever of `CLAUDE.md` / `AGENTS.md` already exists in the repo (edit whichever is present; ask before creating either if neither exists), plus the contents of `docs/agents/issue-tracker.md`, `docs/agents/domain.md`, and (if applicable) `docs/agents/triage-labels.md`. Let them edit before writing, then write.

If an `## Agent skills` block already exists, update it in place rather than duplicating it.

### 4. Done

Tell the user setup is complete and which skills will now read from these files. Re-running this skill is only needed to switch issue trackers or start over.
