# ⏪ ROLLBACK — How to go back if something breaks

> **Short version:** v3.12.0 is on `main` (merged 2026-07-30).
> To undo it, run **`git revert -m 1 da6d215`**. Nothing is lost either way.

---

## 🗂️ The references you have

| Reference | Commit | What it is |
| :--- | :--- | :--- |
| **`main`** | `2378175` | **Current.** v3.12.0 — all fixes. Pushed to GitHub. |
| **tag `v3.12.0`** | `da6d215` | The release point. Immutable — `git checkout v3.12.0` always gets you here. |
| the merge | `da6d215` | One commit containing the whole DXF update — revert this to undo it all |
| pre-update `main` | `7e6b3a1` | The old version (pre-3.11), still in history |

There is now a **single branch** (`main`) plus that tag. The `dxf-text-metrics`
and `v3.7.0-hardening` branches were deleted after merging — every commit they
held is reachable from `main`, so nothing was lost. Old versions are all still in
git history and can be restored.

---

## ✅ Scenario 1 — "The new version misbehaves, put it back"

The whole DXF update went in as one merge, so one command undoes all of it:

```bash
cd ~/Developer/dp-lookup-pro-IP
git revert -m 1 da6d215
rm -f output/.cache_store.json
```

This creates a NEW commit that undoes the update. Nothing is erased and the
history stays honest — the right choice now that `main` is on GitHub.

If you also want GitHub back to the old behaviour:

```bash
git push origin main
```

To look at the old version without changing anything:

```bash
git checkout 7e6b3a1      # detached view of the pre-update code
git checkout main         # back to current
```

> ⚠️ **Expect the first lookup after switching to be slow** (5–13 seconds
> instead of instant). Each version ignores the other's cache, so it refetches.
> That is normal, not a fault.

---

## ✅ Scenario 2 — "I want it gone from history entirely"

```bash
git reset --hard 7e6b3a1
git push --force origin main
```

> ⚠️ **This is the destructive option.** `reset --hard` discards the work, and
> the force-push rewrites GitHub's history. The update is already published, so
> prefer Scenario 1's revert unless you are certain nobody has pulled it.
> The `v3.12.0` tag would still hold the work either way — that is what the tag
> is for, now that the safety-net branches are gone.

---

## ✅ Scenario 3 — "Only one part is wrong, keep the rest"

The riskiest changes are isolated, so they can be reverted individually. Open
`cts_dp_lookup_pro.py` and change **only** the relevant block:

**CRZ detection** — find `crz_restriction_layer_ids` and restore the old list:
```python
crz_restriction_layer_ids = [31, 1118, 2212, 2213, 2214, 2240, 2241, 2242, 2243]
```
⚠️ This reinstates a known bug: CRZ will report `NO` for every plot in Mumbai.

**Dropping a crowded dimension label** — in `export_dxf`, the dimension loop
removes a label it cannot place clear of its neighbours. To keep every label even
when they overlap, delete the `msp.delete_entity(txt_elem)` branch.
⚠️ Overlapping numbers on the sheet can be misread, which is why they are dropped.
Across 27 plots this affects 1 label in 388.

**Abutting road selection** — `nearest_road_geoms(road_geoms, wgs_rings)` ranks
roads by distance to the plot. Replacing it with `road_geoms[:6]` restores the old
behaviour.
⚠️ That reinstates a known bug: the real frontage is pushed out by distant road
polygon rings, so `C-ROAD-ALIGN` ends up empty or wrong.

**Cache expiry** — find `DEFAULT_CACHE_TTL_SECONDS`:
```python
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60   # back to 24 hours
```

**Request timeout** — in `lookup_plot_pro`, change `timeout_seconds: float = 20.0`
back to `10.0`.

After any manual edit, run the tests:
```bash
uv run pytest -q
```

---

## 🔍 How to tell which version is running

```bash
git describe --tags        # v3.12.0 (plus a commit count if you are ahead of it)
grep '^version' pyproject.toml
```

Or run a lookup on a coastal plot — this is the clearest behavioural tell:

```bash
uv run python dp-lookup-pro WORLI 947
```

| Output | Version |
| :--- | :--- |
| `CRZ  YES (CRZ II)` | **v3.7.0 or later** — correct |
| `CRZ  NO (Outside CRZ Buffer)` | **older** — this answer is wrong for a coastal plot |

To confirm you are on **v3.12.0** specifically, audit a generated drawing:

```bash
uv run python tools/audit_dxf.py output/worli_cts_733/plot_G-S_733_worli.dxf
```

On v3.12.0 this prints `CLEAN`, the PLOT DATA panel carries a `MEASURED (BDY)`
row beside `GROSS PLOT AREA`, and `C-ROAD-ALIGN` holds road geometry. On earlier
versions it reports faults, prints one area only, and may draw no road at all.

---

## 🧯 Things that are *not* a fault

Before rolling back, check whether it is one of these:

| Symptom | Cause | What to do |
| :--- | :--- | :--- |
| `Could not reach the MCGM map server (ReadTimeout)` | MCGM rate-limits bursts of lookups | Wait ~30 s and retry. Space bulk lookups ~12 s apart. |
| A lookup takes 13 s, another takes 5 s | MCGM is slow *and variable* across every endpoint | Nothing to fix. The `/export` map image is the slowest single call (5.6–5.9 s) but identify calls range 414 ms–4,470 ms, so no one request dominates reliably. |
| `Plot not found` | Village name must be one of 128 exact names | `BANDRA` is invalid — use `BANDRA-A`…`BANDRA-I`. See `START-HERE.md`. |
| A plot reports `CRZ: YES (CRZ II)` where it used to say `NO` | **The fix working.** The old answer was wrong. | Verify against the generated map image — CRZ II is printed on it. |
| The DXF prints two different plot areas | **Intended.** MCGM's record and MCGM's own digitised polygon disagree — by 6.10% on AMBIVALI 807. | Reconcile both, and the Property Card, before any FSI calculation. |
| A boundary segment has no dimension label | Sub-metre sliver, or a label that could not be placed without overlapping | Expected. Measure the segment in CAD. |
| Area shows as *derived* | MCGM has no approved area for that parcel | Expected. Check `plot_identity.area_source`. |
| First lookup after switching versions is slow | Cache formats differ between versions | Normal. |

---

## 🩺 Health check

To confirm an install is working:

```bash
uv run pytest -q                              # v3.12.0: expect 147 passed
uv run ruff check .                           # expect "All checks passed!"
uv run python dp-lookup-pro BYCULLA 1605      # inland plot, should say CRZ: NO
uv run python dp-lookup-pro WORLI 947         # coastal plot, should say CRZ: YES (CRZ II)
```

If the tests pass and both plots return sensible answers, the install is fine.

---

## 💾 Your data is safe either way

Rolling back **does not touch**:

- `output/` — every report bundle you have generated
- `output/dp-lookups.xlsx` — your master register

Those are excluded from version control, so they survive any branch switch,
revert or reset. The only thing worth deleting is `output/.cache_store.json`,
and only so the version you switch to refetches cleanly.
