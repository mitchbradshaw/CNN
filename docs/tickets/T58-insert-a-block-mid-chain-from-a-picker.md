---
id: 58
title: "Insert a block mid-chain from a + picker"
model: sonnet
size: M
blocked_by: [57]
mutex: [59]
files: ["UI/workspaces/analyse/builder.py", "tests/test_chain_builder.py"]
flags: ['human-verify']
level: 1
unblocks: 0
budget_minutes: 60
---
# 58 — Insert a block mid-chain from a + picker

**Model:** [S] · **Size:** [M]

**What to build:** A `+` sits between every pair of cards and at the end of the chain. Clicking one
opens a picker of every registered block; choosing one inserts it **at that
position**.

Mid-chain insertion is the operation the researcher actually wants — "this needs a
detrend before the SAX" — and today the only way to get it is to delete everything
downstream and rebuild. The chain model has always supported insertion at an index;
no surface has ever offered it.

The picker lists **every** registered block, with incompatible ones **disabled and
the reason shown**, never filtered out. That rule is from Part 1 and it stands: a
researcher learns the type system by being told why a block cannot go there, and
learns nothing at all from a block that quietly is not in the list. The reason text
comes from the existing chain-validation function — it is the same text, relocated.

The picker is opened from a `+` rather than living permanently on the surface. The
old behaviour put twenty always-visible buttons between the researcher and their
chain.

**Blocked by:** 57

**Files/modules touched:** `UI/workspaces/analyse/builder.py`, `tests/test_chain_builder.py`.

**Merge risk:** **MEDIUM.** Shares `builder.py` with T59, which is why the two are mutually
exclusive — either order is fine, both at once is not. Take the reason strings from
the validation function; do not write new ones.

**Acceptance criteria:**
- [ ] A `+` appears between every pair of cards and after the last one.
- [ ] Choosing a block from a `+` inserts it at that position, not at the end.
- [ ] The picker lists every registered block, with incompatible ones disabled.
- [ ] A disabled block shows the reason it cannot go at that position.
- [ ] Inserting mid-chain preserves the steps after it and rebinds anything that pointed at them.
- [ ] A headless test asserts insertion at a middle index produces the expected step order.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
