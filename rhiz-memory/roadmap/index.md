# rhiz-memory — Roadmap notes (Broodforge)

Forward-looking work notes for broodforge. Add a row when you add a note so it
stays discoverable from the instance entry point ([`../_instance.md`](../_instance.md)).

| Topic | Note |
|-------|------|
| `docs/` under Rhizome management (via tessel ↔ rhizome partition/roll-up) | 📌 **Pinned, not started.** Broodforge's large `docs/` tree will one day be managed by the Rhizome method (partitioned into a rhiz-Merkle DAG, rolled up to composite monoliths, transpiled to interactive HTML by tessel). Blocked on the cross-project effort that wires rhizome's partition/roll-up into tessel's compose + md→html pipeline. Canonical record: `david-coneff/rhizome` → `rhiz-memory/roadmap/tessel-rhizome-partition-rollup-integration.md`. Do **not** migrate `docs/` until tessel can round-trip a partition (roll-up → transpile → re-partition) with `doc-graph verify` still passing. |
