# Local-first acceptance and source baseline — 2026-08-23

## Decision

The normal CLI source mode remains **`auto`** and is now accepted as the
operational default: use the active local parcel and planning snapshots first,
then fall back visibly to live MCGM ArcGIS when a local source cannot answer.
Strict `--source local` and the verification escape hatch `--source live`
remain available.

This is an operational screening source, not a certified legal boundary or an
official DP Remarks plan.

## Refresh and activation record

The pre-refresh upstream check detected five parcel records affected by a
change and one changed planning layer:

- Layer 13 added ObjectIDs `244326`, `244327` and `244328` (MOGRA CTS 60–62)
  and changed ObjectIDs `75591` and `86800` (MOGRA CTS 59 and 63).
- Planning layer 85, `Relocation_Reconstitution`, changed from 120 to 114
  records; ObjectIDs 13457–13462 were removed.
- The unchanged layer-85 maximum edit date did **not** detect that inventory
  change. This confirms that maintenance must compare inventories as well as
  timestamps.

New immutable snapshots were downloaded, verified, diffed and then activated.
The earlier snapshots remain available for rollback.

| Dataset | Active snapshot | Records | Content hash |
| :--- | ---: | ---: | :--- |
| Parcels | 2 | 135,345 / 135,345 | `985f3d9790d7dacdbce34cdd6ba710ef5d8931c61241b785fd54b3db10966ff5` |
| Planning | 3 | 65,598 / 65,598 across 52 layers | `10217c44677a33a304be5d9ff59985f2db51d623ab713fb3132c3d8095e734a9` |

Both snapshot verifiers returned zero errors. Planning retains the three known
official Layer 47 records with empty geometry as warnings; no polygon is
invented for them.

## Baseline health and upstream fingerprints

The post-activation health run at `2026-08-22T22:23:55.864071+00:00` recorded:

- SQLite integrity `ok`, zero foreign-key violations and no critical finding;
- parcel inventory equality, no missing geometry, inventory ID or validation
  record;
- planning registry equality, 52/52 canonical layers and no missing geometry
  beyond the three explicitly retained source warnings;
- 11,954 parcel features without a complete village/CTS identity, 3,050
  multi-feature identities and 12,741 features without a recorded area;
- no active full plot-intelligence build and no configured certified-source
  enrichment. These are visible `attention`/`not_configured` states, not source
  database corruption.

The database occupies 2,259,247,104 bytes (about 2.10 GiB) because it currently
preserves both the former and current immutable parcel/planning snapshots for
rollback.

The final read-only upstream check at
`2026-08-22T22:24:21.169652+00:00` downloaded no feature geometry and returned
`unchanged`:

| Fingerprint | Local active value | Live result |
| :--- | :--- | :--- |
| Parcel record count | 135,345 | Match |
| Parcel ObjectID inventory SHA-256 | `259f5da8c0c90a58a65d8511e548e4f18b8aeb442411f4c71189a6da677aafdb` | Match |
| Parcel metadata SHA-256 | `ccc3e658f4a5d0a08b7e701a02f05316eb84878aa576bbee0a16829302365fa7` | Match |
| Parcel maximum edit signal | `1787309290000` | Match |
| Planning registry SHA-256 | `822f559ede4f9382d3d1e8f4ab8cf44668be406077e8a49c1b8014d017064088` | Current registry |
| Planning layer fingerprints | 52 canonical layers | 52 unchanged; 0 changed; 0 unknown |

A matching fingerprint cannot prove that coordinates under an unchanged
ObjectID never changed. The annual forced full download remains the backstop.

## 23-CTS acceptance audit

The deterministic corpus used seed `20260823`: five changed-record controls,
three constraint-rich controls, two multipart controls and thirteen seeded
random identities. It covers 18 villages and 13 wards.

For each CTS identity, the audit independently compared local and live:

1. normalized village/CTS identity, source ObjectID set and part count;
2. canonical raw geometry SHA-256;
3. recorded plot area and projection-corrected calculated boundary area;
4. primary zoning;
5. reservations, designations, modifications, CRZ and Metro results; and
6. normal implicit-`auto` output behavior, source evidence and artifact
   readability.

Result: **23/23 accepted in 78.423 seconds**. All comparisons passed. Twenty-one
cases produced and opened all seven bundle artifacts; their shared Excel
register rows were also validated. Two cases had no usable zoning in either
local or live Layer 0 and correctly failed closed with zero artifacts instead
of producing a misleading report.

| Village / CTS | Parts | Geometry hash | Recorded / calculated m² | Zone | Constraints | Outcome |
| :--- | ---: | :--- | ---: | :---: | :--- | :--- |
| MOGRA 59 | 1 | `afe2cdbc5cf1…` | 2,742.92 / 3,120.94 | R | — | Bundle |
| MOGRA 60 | 1 | `6507eeec0f16…` | 2,742.92 / 23.45 | R | — | Bundle |
| MOGRA 61 | 1 | `c1ffc2a207b5…` | 2,742.92 / 170.64 | R | — | Bundle |
| MOGRA 62 | 1 | `ec034f99e6d4…` | 2,742.92 / 9.18 | R | — | Bundle |
| MOGRA 63 | 1 | `e8794b68524b…` | 1,952.92 / 1,969.07 | R | 1 reservation | Bundle |
| MALABAR HILL 518 | 1 | `2412d9f746ce…` | — / 2,450.16 | R | 3 designations | Bundle |
| BYCULLA 1605 | 1 | `172202289c7c…` | 1,877.87 / 1,877.87 | R | 1 designation, 1 modification, Metro | Bundle |
| WORLI 733 | 1 | `eb023af14349…` | 1,317.74 / 1,317.73 | R | 3 CRZ results | Bundle |
| MAJAS 99 | 2 | `443982463752…` | — / 1,543.32 | R | 2 reservations, Metro | Bundle |
| MOHILI 638/3 | 2 | `bdc9d096ce4e…` | 3,129.00 / — | I | 1 reservation | Bundle |
| CHARKOP 566 | 1 | `47fe3659ea47…` | 818.30 / 818.30 | NDZ | — | Bundle |
| MULGAON 215 A | 1 | `bea098a48456…` | 3,717.53 / 3,810.59 | I | — | Bundle |
| POISAR 651 | 1 | `0b8ffdb1df1e…` | 119.38 / 3.59 | — | — | Correct fail-closed |
| AMBIVALI 838 (PT) BLDG.NO-61 | 1 | `285244cf188d…` | 776.00 / 785.12 | R | — | Bundle |
| DADAR-NAIGAON 913 TO 914 | 1 | `3d5fbc846ba8…` | 2,805.20 / 2,805.20 | R | 1 designation | Bundle |
| DAHISAR 2349 | 1 | `9b2466cb77d6…` | 1,403.02 / 1,403.02 | R | 1 designation | Bundle |
| VERSOVA 1374B/312 | 1 | `8c97d06dbc0c…` | 174.00 / 110.12 | R | — | Bundle |
| MAROL 1397 B/2 | 1 | `e6c12ac8c149…` | 3,017.35 / 241.45 | R | Metro | Bundle |
| BANDRA-A 434 | 1 | `b2697fd2fbcc…` | 42.44 / 42.48 | R | 2 CRZ results | Bundle |
| KIROL 263 | 1 | `dbe6fb63842a…` | 418.34 / 418.34 | R | — | Bundle |
| MALABAR HILL 1A/395 | 1 | `10773e4eea94…` | — / 1,397.74 | R | 2 CRZ results | Bundle |
| MANORI 174 | 1 | `f08958f072fc…` | — / 1,717.34 | — | 4 CRZ results | Correct fail-closed |
| PAHADI GOREGAON-E 207 | 1 | `736137f0bc2b…` | 515.44 / 515.44 | C | — | Bundle |

The large MOGRA, POISAR and MAROL area differences exist identically in local
and live MCGM data. They are source-quality findings, not parity failures. The
tool retains both values and flags the difference; it never reshapes the
boundary to force agreement. MOHILI 638/3 likewise retains its recorded area
while showing calculated area as unavailable because its combined geometry
cannot support that assessment.

## Reproduction

```bash
uv run python tools/acceptance_audit.py \
  --database data/mcgm-layer13.sqlite \
  --output-dir /tmp/dp-lookup-acceptance-2026-08-23 \
  --sample-size 23 --seed 20260823 --timeout 30 --delay 0.75 \
  --json-report /tmp/dp-lookup-acceptance-2026-08-23/report.json
```

The first draft of the new audit harness stopped after eight cases because it
used an obsolete field name on the area-assessment dataclass. The harness was
corrected before the reported run; no application lookup, snapshot or output
failed because of that harness defect.

After the corpus run, two real human-output smoke tests confirmed the source
labels. Normal `WORLI 733` displayed local parcel snapshot 2 and planning
snapshot 3; the same lookup against an intentionally missing database displayed
both sources as `Live MCGM ArcGIS · fallback`, explained the fallback, and
completed all seven files.
