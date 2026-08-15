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
