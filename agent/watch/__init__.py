"""Watch Mode (Phase 8, spec's Loop 5 -- the outer detection loop).

Instead of a human declaring "I'm about to rename column X" (declared mode),
watch mode periodically snapshots a table's live schema, diffs it against a
previously stored snapshot, and -- if it detects a change -- triggers the
same pipeline declared mode uses, for human review (never unattended).
"""
