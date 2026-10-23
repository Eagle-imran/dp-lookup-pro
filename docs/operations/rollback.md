# Rollback and recovery

Recover code, source snapshots and derived intelligence independently. Inspect
local changes before switching versions, and keep the current operational data
and report folders when diagnosing a code regression.

## Identify the running code

```bash
git status --short --branch
git log -1 --oneline
git describe --tags --always
uv run dp-lookup-pro --version
git branch -avv
git worktree list
```

The package still reports `3.14.0` while `main` contains subsequent unreleased
changes. Use the commit ID as well as the package version when reporting a fault.

## Recovery references

| Reference | Commit | Purpose |
| :--- | :--- | :--- |
| `main` / `origin/main` | Current integration history | Current application; inspect its tip rather than assuming a fixed release commit |
| `refs/tags/checkpoint-pre-2026-08-18` | `97b8e62` | Preserved pre-modularization checkpoint, synchronized to origin |
| `refs/tags/v3.14.0` | `2ca85e9` | Original modular-package version; this tag is currently local to the maintainer checkout |
| `refs/tags/v3.12.0` | `da6d215` | Published Git tag for the earlier DXF hardening release |

The redundant checkpoint branch has been removed; the tag preserves the same
commit without a second branch to maintain. Use the full `refs/tags/...`
spelling in older clones that still have a same-named branch. Confirm a clone's
inventory with `git branch -a` and `git tag --list`. The former
`dxf-text-metrics` and `v3.7.0-hardening` branches were merged and removed; their
commits remain reachable from `main`.

Pushing a `v*` tag starts the trusted publishing workflow. Do not publish a
historical local tag merely to synchronize a clone; release publication is a
separate operation.

## Inspect an old version safely

Start from a clean checkout or commit your work on its existing branch. Then
inspect a specific reference without changing the branch pointer:

```bash
git switch --detach refs/tags/v3.14.0
# Inspect the code and run its own documented checks.
git switch main
uv sync --frozen --all-extras --dev
```

For the earlier checkpoint, substitute
`refs/tags/checkpoint-pre-2026-08-18`. Older code may predate the local database
schemas. Use a separate, explicitly selected database copy for an old version;
Git does not version or roll back SQLite contents.

## Revert a code regression

Find the specific change with `git log` and review it with `git show`. Create a
repair branch from current `main`, then use `git revert COMMIT_ID` for an
ordinary commit. For a merge commit, review both parents before choosing a
mainline; `git revert -m 1 MERGE_COMMIT_ID` keeps the first parent's history.

Run the checks in [CONTRIBUTING.md](../../CONTRIBUTING.md) and review the diff
before merging the repair. Reverting the historical DXF merge is not a general
rollback for newer changes to the modular application. Avoid rewriting shared
history to recover an ordinary regression.

Current implementation boundaries are listed in the
[architecture guide](../architecture/overview.md). The public
`cts_dp_lookup_pro.py` file is a compatibility facade; new fixes belong in the
owning module under `dp_lookup/`.

## Roll back source snapshots

Use the supported lifecycle commands, never manual edits to SQLite:

```bash
dp-lookup-pro db health
dp-lookup-pro db parcels status
dp-lookup-pro db planning status
dp-lookup-pro db parcels rollback
dp-lookup-pro db planning rollback
dp-lookup-pro db health
dp-lookup-pro plots check
```

Each rollback is independent and activates the previous finalized version in
that dataset's lifecycle. Roll back only the affected source. If intelligence
was active, activate a verified full build matching the newly active source
IDs, or rebuild it. See [planning snapshots](planning-snapshots.md) and
[plot intelligence](../guides/plot-intelligence.md).

## Diagnose before rebuilding

| Symptom | First check |
| :--- | :--- |
| Timeout or unavailable map imagery | Space live requests and retry; the report exposes warnings and completeness |
| Plot not found | Use an exact revenue village name from `--list-villages` and verify the CTS number |
| Recorded and calculated areas differ | Review `plot_identity.area_assessment`, source documents and quality flags |
| No active intelligence build | Build, verify and activate a full build; ordinary lookup does not require one |
| A cache hit appears stale | Pass `--no-cache` to recompute using the selected sources |
| Source snapshots appear stale | Run `db health` and the read-only `db check-upstream` before a staged refresh |

`--no-cache` does not refresh source snapshots. Parcel/planning source selection
is controlled by `--source`, `--database` and active snapshot pointers.

## Preserve operational files

`data/`, `output/` and `.venv/` are ignored by Git. A normal branch switch or
revert does not remove them, but Git also cannot restore them after deletion.
Preserve SQLite databases, retained snapshots, certified-source documents,
report bundles and `output/dp-lookups.xlsx` independently. Do not use
`git clean -fdx` on an operational checkout.
