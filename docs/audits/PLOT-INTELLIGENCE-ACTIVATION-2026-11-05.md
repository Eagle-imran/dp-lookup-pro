# Plot-intelligence activation — 2026-11-05

## Publication result

Full local intelligence build **14** is verified and active. It uses the
existing parcel snapshot **3** and planning snapshot **5**, with algorithm
**plot-intelligence/1.4.1**, full evidence and neighbour analysis. No MCGM
source refresh was performed for this publication; source data remains the
verified 2026-10-23 dataset.

| Measure | Result |
| :--- | ---: |
| Queryable village/CTS identities | 119,548 |
| Published intelligence records | 119,548 |
| Source references | 626,130 |
| Derivation errors | 0 |
| Recomputed fact checksums | 119,548 matching |
| Missing source references | 0 |
| Stratified/control lookup comparisons | 36 passing |
| Build workers | 1 |
| Build duration | 3,470.868 seconds (57 minutes 51 seconds) |
| Local health critical findings | 0 |

Source fingerprint:
`1ae2bc98f619456e1ccd381a2928337292021e6de368652c4a46c91f1aa6f0cc`.
The build finalized at `2026-11-05T10:14:18.163191+00:00`; activation followed
complete offline acceptance. The active source IDs, algorithm and fingerprint
align, `ready_for_operational_use` is true, and no rebuild is indicated.

## Verification and quality boundaries

The offline acceptance tool independently checked exact identity-set equality
against the eligible source records, resolved every normalized evidence
reference to its pinned parcel/planning snapshot, and recomputed every fact
checksum after reconstructing normalized reference attributes.

The 36 deterministic stratified/control plots matched normal local lookup for
identity, area assessment, zoning, planning percentages/totals, CRZ, Metro,
roads, neighbours and expanded-evidence completeness. One control lacked usable
zoning: normal lookup correctly rejected a report while intelligence retained
that plot as `review_required`. Source-intersection square metres use the
calculated boundary basis; plot totals use the selected recorded/calculated
area basis. These bases are intentionally kept distinct.

| Intelligence confidence | Records |
| :--- | ---: |
| verified | 78,863 |
| qualified | 34,245 |
| review_required | 6,440 |

These labels describe source and analysis quality, not legal certification.
The three known empty-geometry Designation records remain source warnings.
Records lacking complete village/CTS identity remain in the source archive and
are excluded from the queryable identity set. No source geometry, recorded area
or missing identity was invented to make publication pass.

## Public CLI acceptance

After activation, default commands (without `--build-id`) passed:

```bash
uv run dp-lookup-pro plots analyze WORLI 733 --json
uv run dp-lookup-pro plots search --village WORLI --zone R --min-area 2000 \
  --max-encumbered 10 --has-reservation no --limit 5 --json
uv run dp-lookup-pro plots compare WORLI:733 WORLI:983 --json
uv run dp-lookup-pro plots check --json
```

The filtered search returned five matching records. The comparison returned
both requested plots, with no missing identities: WORLI 733 at 1,317.74 m² and
WORLI 983 at 9,780.74 m², both primary zone R. Individual confidence and area
assessment remain available; the search is a mapped planning screen.

Negative cases also passed: an unknown plot and invalid result limit return
nonzero status with valid JSON errors, and a comparison containing an unknown
identity explicitly lists it as missing. All acceptance queries used local
data and made no network requests. SQLite integrity passes with no foreign-key
violations; health retains the known source-quality attention states.

## Defects corrected before completion

- Retain the selected road layer/ObjectID as a `road_access` reference.
- Preserve reference policy/warning metadata and deterministic ordering when
  combining archived reference metadata with normalized attributes.
- Stop worker loops on interruption while retaining completed records for
  resumption. An earlier unpublished build is retained as failed/superseded.
- Honor `--json` for argument and query failures in intelligence commands.

Algorithm 1.4.1 prevents publishing earlier derivations lacking the corrected
road provenance. Existing source archives and historical intelligence builds
remain available. No source-data refresh, FSI feature, web interface or report
export extension was introduced by this publication.

## Reproduce acceptance

```bash
uv run python tools/intelligence_acceptance.py \
  --database data/mcgm-layer13.sqlite --require-active --sample-size 25 \
  --json-report /tmp/intelligence-acceptance.json
```

The complete offline suite passes 573 tests at 84.37% coverage; Ruff, the shared
formatter and strict mypy pass. CI results are attached to draft PR #6.

The operational database and generated JSON reports remain outside Git. Code,
regression tests and this audit are on `codex/development`. PR #6 remains a
draft and merging is on hold; main has not been changed by this publication.
