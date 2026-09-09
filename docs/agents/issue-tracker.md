# Issue tracker

**This repository has no issue tracker.**

Work is specified by ticket files under `docs/tickets/`, one per ticket, with YAML front-matter.
The originating spec for any review is **always passed by path** — either by the ticket runner
(`docs/tickets/TNN-*.md`) or by the person invoking the review.

Do **not** run `/setup-matt-pocock-skills` to configure one. Do not search for issue references in
commit messages; commit messages carry a ticket id prefix (`T14: …`) which maps directly to the
matching file in `docs/tickets/`.

If a review is invoked with no spec path and the branch name does not resolve to a ticket file, the
Spec axis reports "no spec available" and stops. It does not ask.

---

## Wayfinder effort: GitHub Issues

**Scope of this section: the UI rebuild wayfinder map, and nothing else.** Everything above still
holds for build tickets and for `/code-review` — specs are still resolved by path from
`docs/tickets/`, and no skill should hunt commit messages for issue references. This section adds
one narrow exception: the wayfinder **map** and its **decision tickets** live as GitHub issues on
`mitchbradshaw/CNN`, because wayfinder's frontier is only legible when the tracker renders blocking
edges natively.

Decision tickets are not build tickets. A decision ticket asks a question whose resolution is a
choice; a `docs/tickets/TNN-*.md` file specifies a vertical slice to build. They do not mix, and a
wayfinder ticket never becomes a build ticket in place — the map produces decisions, and a separate
`/to-tickets` pass turns the resulting spec into `docs/tickets/` files.

**Prerequisite: the `gh` CLI.** It is not currently installed on this machine. Install it
(`winget install --id GitHub.cli`) and run `gh auth login` before invoking wayfinder. Without it,
fall back to wayfinder's local-markdown tracker under `.scratch/` and say so explicitly rather than
inventing a third convention.

### Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Destination / Notes /
  Decisions-so-far / Not-yet-specified / Out-of-scope body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues
  endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put
  `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>`
  (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add
  an edge with
  `gh api --method POST repos/mitchbradshaw/CNN/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`,
  where `<blocker-db-id>` is the blocker's numeric **database id**
  (`gh api repos/mitchbradshaw/CNN/issues/<n> --jq .id`, *not* the `#number` or `node_id`). GitHub
  reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where
  dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child
  body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's
  sub-issues / task list), drop any with an open blocker
  (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an
  assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a
  context pointer (gist + link) to the map's Decisions-so-far.
