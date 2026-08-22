# Database maintenance check — 2026-08-23

## Scope

This is the first validation record for the read-only `db health` and
`db check-upstream` workflow. The local database remained unchanged. The live
check requested ArcGIS layer metadata, edit statistics and ObjectID inventories
only; it did not request feature geometry or activate a snapshot.

## Local health result

Overall status: **ATTENTION**

| Component | Result | Evidence |
| --- | --- | --- |
| SQLite | Healthy | Integrity check passed; no foreign-key violations |
| Parcel snapshot | Attention | Active snapshot 1 is complete: 135,342/135,342 records |
| Planning snapshot | Attention | Active snapshot 2 is complete: 52 layers and 65,604/65,604 records |
| Plot intelligence | Attention | One sample build exists; no full build is active |
| Enrichment | Not configured | No Property Card, CTS plan, measurement or survey records are registered yet |

Review items retained from the source are 11,954 parcel features without a
complete village/CTS identity, 3,050 village/CTS identities represented by more
than one source feature, and three planning geometry warnings already preserved
by the planning snapshot manifest. These do not mean SQLite or the active source
snapshots are corrupt.

## Live upstream result

Checked at `2026-08-22T20:01:37.580004+00:00`
(`2026-08-23 01:31:37` Asia/Kolkata).

Overall status: **CHANGED**

### Parcel source

| Signal | Local active snapshot | Live MCGM | Result |
| --- | ---: | ---: | --- |
| Record count | 135,342 | 135,345 | Changed |
| ObjectID inventory hash | `61f671a2311c…` | `259f5da8c0c9…` | Changed |
| Data-contract metadata hash | `ccc3e658f4a5…` | `ccc3e658f4a5…` | Match |
| Maximum `LAST_EDITED_DATE` | `1787227458000` | `1787309290000` | Changed |

### Planning source

Fifty-one planning layers matched. Layer 85, `Relocation_Reconstitution`,
changed:

| Signal | Local active snapshot | Live MCGM | Result |
| --- | ---: | ---: | --- |
| Record count | 120 | 114 | Changed |
| ObjectID inventory hash | `f55c89a4f167…` | `47607ee0d5df…` | Changed |
| Data-contract metadata hash | `856a4248eb8f…` | `856a4248eb8f…` | Match |
| Maximum `LAST_EDITED_DATE` | `1787228664000` | `1787228664000` | Match |

The unchanged maximum edit timestamp on layer 85, despite a changed inventory,
demonstrates why the workflow never relies on a layer date alone.

## Decision

No automatic update or activation was performed. The next maintenance action is
to build new parcel and planning snapshots in the existing staging lifecycle,
verify them, review the parcel and layer-85 diffs, and activate only after that
review. The current active snapshots remain reproducible and usable until that
explicit decision.

Even when a future lightweight check reports no change, perform an annual full
rebuild: matching ObjectIDs and timestamps are strong operational evidence but
cannot prove that every coordinate or attribute under an existing ObjectID is
unchanged.
