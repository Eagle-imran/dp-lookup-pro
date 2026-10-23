# Repository maintenance — 2026-10-23

## Scope and result

Refresh project tooling, restore the failing main-branch formatting gate,
correct obsolete documentation, synchronize the main branch and remove merged
branch clutter. The completed baseline is `e375807`; the remaining development
scope is recorded in [development status](../project/development-status.md).

## Toolchain

| Component | Updated version |
| :--- | :--- |
| uv, local and CI | 0.13.5 |
| GitHub CLI | 2.103.0 |
| setup-uv action | 10.3.2, pinned to `07a047e608db84b3d8c06cd9a7c7dcc9c355c18e` |
| Ruff | 0.17.2 |
| mypy | 2.4.0 |
| Development Python | 3.15.1 |
| Installed Python patch runtimes | 3.11.17, 3.13.17, 3.14.9, 3.15.1 |
| pytest / pytest-cov | 9.1.1 / 7.1.0 |
| pip-audit / Hatchling | 2.10.1 / 1.32.4 |
| Pillow / certifi | 13.0.0 / 2026.10.23 |

All locked packages were resolved to current compatible stable releases. The
package now requires Python 3.11+, Pillow 13+ and certifi 2026.10.19+ so an
unlocked install also gets the patched image decoder and CA bundle.

## Verification

- 539 offline tests passed locally on Python 3.11 and 3.15.
- The Python 3.13 coverage run passed at 84.19%, above the 83% gate.
- Ruff, the shared scoped formatter and strict mypy passed.
- Runtime audits on Python 3.11 and 3.13 reported no known vulnerabilities.
  The complete local development environment audit checked 61 packages and
  reported no known vulnerabilities.
- Wheel metadata, required resources and source-distribution tools were checked;
  both distributions installed and ran in clean Python 3.15 environments.
- [Main CI](https://github.com/Eagle-imran/dp-lookup-pro/actions/runs/39955887396)
  passed on Python 3.11, 3.13, 3.14 and 3.15, including typing, coverage,
  dependency audit and clean packaging/install checks. CodeQL passed as well.

The package remains at version 3.14.0 with unreleased maintenance commits.
No release or PyPI publication was performed. The local `v3.14.0` tag was not
pushed because version-tag pushes start the trusted publishing workflow.

## Git and local cleanup

Maintenance PR #5 incorporated dependency PRs #1 and #4; all three are merged.
Only `main` and `codex/development` remain as local and remote branches.
The older checkpoint branch was replaced by its equivalent synchronized tag.
The repository has one worktree and no stashes or submodules.

Removed disposable development caches and macOS metadata. Operational SQLite
data, source manifests, report bundles, Excel registers, local settings and
retained rollback snapshots were preserved. The separate empty "DP Lookup
Audit" repository was not modified.

## External source and alert status

The read-only upstream check downloaded no geometry and found a parcel count
increase of 20 plus changes in six planning layers. A staged source refresh
was started without replacing the active snapshots; publication is tracked in
the development status document.

GitHub's dependency SBOM reports the new patched versions, including Pillow
13.0.0, urllib3 2.8.0, pytest 9.1.1 and filelock 4.2.4. At the post-merge check,
the alert API still returned 43 historical alerts whose version requirements
referenced old lockfile versions, including Pillow 11.3.0. No alert was
dismissed to hide that discrepancy; its server-side reevaluation is separate
from the passing current lockfile audits.
