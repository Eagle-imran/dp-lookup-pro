# Targeted parcel and planning update — 2026-10-23

## Result and scope

Activated parcel snapshot **3** and planning snapshot **5** after verification.
No full geometry refresh was run for this update. Reused the already-staged
parcel snapshot, independently rechecked its 66 added/edited payloads, and
confirmed removals against the current inventory. Downloaded only planning
layers **81, 85, 92, 192, 194 and 2400**; copied the other 46 layers locally from
the former active planning snapshot 3.

| Dataset | Former active | New active | Records |
| :--- | ---: | ---: | ---: |
| Parcels | 2 | 3 | 135,345 → 135,365 |
| Planning | 3 | 5 | 65,598 → 65,624 across 52 layers |

The parcel content hash is
`cb83282b9660116b3017f8b0308442427895657c584d65d737c352eb6821f481`.
The planning content hash is
`641a46b40eff199280d8f2c8e00a28bb40f9ed9d6fe0a89b81e555fce8e1bcd2`.

## Parcel verification

- 23 added source records, 43 edited records and 3 removals: net +20 records.
- All 66 added/edited source payloads match fresh live attributes and exact
  boundary coordinates, with zero mismatches.
- The other 135,299 raw records are byte-for-byte identical to snapshot 2.
- Before/after inventory, schema and edit-signal checks match staged snapshot 3.
- Full local inventory equality, snapshot validation and database integrity pass.
- 119,548 village/CTS identities are queryable. An earlier boundary-area preflight
  succeeded for all of them; that is an analysis check, not boundary certification.

## Planning verification

| Layer | Former count | New count | Added | Edited | Removed |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 81 — Road Realignment | 26 | 27 | 1 | 0 | 0 |
| 85 — Relocation/Reconstitution | 114 | 118 | 4 | 0 | 0 |
| 92 — DCPR 2034 Corrections | 73 | 78 | 5 | 0 | 0 |
| 192 — Corrections Notification | 300 | 302 | 2 | 0 | 0 |
| 194 — Survey RoadLines | 3,424 | 3,425 | 1 | 0 | 0 |
| 2400 — Amenities | 603 | 616 | 13 | 1 | 0 |

Fetched 4,566 records in the selected layers. Compared all 27 added/edited
payloads independently against live source attributes and geometry: zero
mismatches, missing records or request errors. All 46 copied layers retain their
original content hashes, inventories and raw JSON. Their source provenance and
originating snapshot are retained; they are not described as newly downloaded.

The incremental builder checks every layer's lightweight upstream fingerprints
before and after downloading the selected layers. It rejects omitted changed or
unknown layers, changed source fingerprints, and incompatible resume state.
The complete new snapshot passes all 52 inventories and local validation.
The three pre-existing empty-geometry Designation records (1158, 1159, 4817)
remain visible source warnings.

## Active-source acceptance

The final read-only upstream check at `2026-10-23T14:33:00.624320+00:00` reports:

- parcels unchanged; planning unchanged across all 52 layers;
- zero changed or unknown planning layers, and no refresh currently indicated;
- no geometry downloaded by the check.

Database health reports integrity `ok`, zero foreign-key violations and zero
critical findings. Source-quality attention remains: 11,951 parcel records lack
a complete village/CTS identity, 12,741 lack a recorded area, and 3,047 identities
contain multiple source features. These source records were preserved.

Four strict-local acceptance cases passed without network requests: EKSAR
1515A/1, MULGAON 8B, WORLI 983 and WORLI 733. They use parcel snapshot 3 and
planning snapshot 5, including local road, adjacency and expanded planning
adapters. This update did not repeat the historical live image/report-bundle
acceptance audit or activate citywide plot intelligence.

## Code, retention and limits

`db planning build --layers 81,85,92,192,194,2400` stages this incremental form;
verification and activation remain separate commands. Regression coverage
includes exact copies and spatial indexes, selected-only downloads, removal of
old selected-layer records, omitted changes, source drift, resume isolation,
activation and rollback. The complete suite passes **567 tests at 84.30% coverage**;
Ruff, the shared formatter and strict mypy pass.

Former active snapshots remain available for rollback. The abandoned full
planning snapshot 4 retains its partial payloads in `failed` state, explicitly
superseded by snapshot 5 so it cannot be resumed accidentally. Operational data
and manifests remain ignored by Git. Code and documentation live on
`codex/development`; main remains the synchronized maintenance baseline.

Matching inventories, schemas and edit signals cannot prove every coordinate
under an existing ObjectID never changed. An incremental update preserves that
limitation; periodic full verification remains the backstop. These results
establish source parity and operational screening, not statutory approval.
