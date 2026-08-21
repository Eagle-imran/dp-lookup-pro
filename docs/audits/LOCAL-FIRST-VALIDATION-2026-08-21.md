# Local-first lookup validation — 2026-08-21

## Decision

The CLI may safely default to `auto`: active local parcel and planning snapshots
first, with visible live fallback. Core planning and optional evidence are now
local-first after their separate activation gate. Road probes, rendered DP maps
and satellite imagery remain live. Programmatic dependency defaults remain live
for compatibility.

## Source-part parity audit

- Deterministic seed: `20260821`
- Active parcel snapshot: `1`
- Active planning snapshot: `2` (52 layers; 65,604 records)
- Snapshot inventory: 135,342 source features
- Selection: 30 CTS identities across 18 wards
- Coverage: duplicate/multipart, smallest-area, largest-area, highest-vertex
  irregular, and ward/village spread cases
- ArcGIS request: POST, `outFields=*`, geometry enabled, `outSR=102100`
- Source parts compared: 274
- Live parts returned: 274/274
- Exact attribute matches: 274/274
- Exact geometry matches: 274/274
- Missing or mismatched parts: 0

The 30 identities were COLABA 479; CHEMBUR 114(PT); MALVANI 3525(PT);
OSHIWARA 1(PT); KANJUR-W 585; AKURLI 174X; AMBIVALI 150 A/1, 150A/3,
150A/4 and 3A/6; MAGATHANE 168; KOLEKALYAN 7721 and 2184; OSHIWARA 1;
KANJUR-E 657; PAREL-SEWERI 145 and 2/207; WORLI 224 and 741/1; PASPOLI
69; MALVANI 1471; COLABA 269; MANDVI 65; BHULESHWAR 2884; MALABAR HILL
934; BYCULLA 871; MATUNGA 385; DHARAVI 64; BANDRA-C 912; and MULGAON
46/30.

## End-to-end comparison

Five cases were run through both implicit `auto` and explicit `live`, for ten
fresh runs total:

| Case | Purpose | Result |
| :--- | :--- | :--- |
| WORLI 741/1 | normal single part | both complete; identity, area and planning matched |
| MANDVI 65 | 86.89 m² small plot | both complete; identity, area and planning matched |
| KANJUR-E 657 | three-part, 3,901-vertex irregular identity | both complete; auto evaluated combined geometry |
| WORLI 224 | four-part irregular identity | both complete; auto evaluated combined geometry |
| COLABA 479 | 74-part stress case | both complete; auto preserved all parts and derived the conflicting area from the combined boundary |

Every run returned exit code 0, complete metadata, and all seven requested
artifacts. Every implicit-auto parcel run used
`local_snapshot_attribute_query`. Planning was still live during this earlier
parcel-only comparison; the later planning gate is recorded below.

Planning differences on multipart identities are intentional: the local path
combines every exact Layer 13 source feature for the village/CTS identity,
whereas the legacy live query selects its first returned feature. Reports now
state the source-part count, ObjectIDs, combined-geometry scope, snapshot ID,
snapshot date, and any recorded-area conflict.

## Planning snapshot follow-on gate

After the parcel audit, planning snapshot 2 was downloaded, verified and
activated independently. It contains 52/52 canonical layers and 65,604/65,604
records, with zero errors. Three official Designation records (1158, 1159 and
4817) have empty rings and remain explicit non-spatial warnings.

A seeded live/local audit matched core planning on 15/15 CTS cases and full
optional evidence on 5/5 cases. Fresh WORLI 733, COLABA 1/600 and VILE PARLE
1449 CLI runs used local planning and local optional evidence, returned no
warning, and generated all seven artifacts. Full details are in
[PLANNING-SNAPSHOT-VALIDATION-2026-08-21.md](PLANNING-SNAPSHOT-VALIDATION-2026-08-21.md).

## Failure and consistency checks

- Missing, corrupt, inactive and unreadable databases fall back live in auto.
- A local identity miss falls back live.
- Missing, invalid, query-failing or over-210-day planning snapshots fall back
  live in auto.
- Fallback reason is recorded in report notes and parcel evidence.
- `--source local --database PATH` remains strict for parcel and planning reads.
- `--source live` bypasses both local snapshots.
- Each run pins one parcel snapshot and one planning snapshot.
- Report caches include the database path and both snapshot IDs.
- Snapshots older than 210 days remain usable but produce a visible warning.
- A real missing-database smoke run completed with live parcel evidence and all
  seven exports.

## Engineering gates

- Ruff: clean
- Strict mypy: clean across 29 production modules
- Tests: 399 passed
- Coverage: 84.48% (80% gate)
- Resource warnings: treated as errors and clean
- Wheel and source distribution: built successfully
- Generated 1.0 GiB combined SQLite database: ignored by Git and absent from
  the wheel

Raw transient audit output was written under `/tmp` during validation. This
document is the durable repository record; source counts and parity should be
re-measured after each future snapshot update.
