# ⏪ ROLLBACK — How to go back if something breaks

> **Short version:** your old working version is saved and untouched.
> To go back to it, run **`git checkout main`**. Nothing is lost either way.

---

## 🗂️ The two versions you have

| Name | Commit | What it is |
| :--- | :--- | :--- |
| **`main`** | `cb6df26` | Your previous working version. Untouched. |
| **`v3.7.0-hardening`** | `13125de` | The 2026-07-28 update (CRZ, roads, areas, caching, tests). |

Both live on your Mac. Switching between them changes the files in the folder —
it does not delete anything.

---

## ✅ Scenario 1 — "The new version misbehaves, put it back"

This is the common case, and it is one command:

```bash
cd ~/Developer/dp-lookup-pro-IP
git checkout main
```

Then clear the cache, because the two versions store it differently:

```bash
rm -f output/.cache_store.json
```

You are now running exactly what you had before. To return to the new version
later:

```bash
git checkout v3.7.0-hardening
```

> ⚠️ **Expect the first lookup after switching to be slow** (5–13 seconds
> instead of instant). Each version ignores the other's cache, so it refetches.
> That is normal, not a fault.

---

## ✅ Scenario 2 — "I already merged it into `main` and want it undone"

If the update has been merged and you want to reverse it while keeping a record:

```bash
git revert 13125de
```

This creates a **new** commit that undoes the changes. Nothing is erased, and
the history stays honest — preferred if the code has been shared with anyone.

If it has **not** been shared and you want it gone entirely:

```bash
git reset --hard cb6df26
```

> ⚠️ `reset --hard` permanently discards work after that commit. Only use it if
> nobody else has the code.

---

## ✅ Scenario 3 — "Only one part is wrong, keep the rest"

The riskiest changes are isolated, so they can be reverted individually. Open
`cts_dp_lookup_pro.py` and change **only** the relevant block:

**CRZ detection** — find `crz_restriction_layer_ids` and restore the old list:
```python
crz_restriction_layer_ids = [31, 1118, 2212, 2213, 2214, 2240, 2241, 2242, 2243]
```
⚠️ This reinstates a known bug: CRZ will report `NO` for every plot in Mumbai.

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
git branch --show-current
```

Or run a lookup on a coastal plot — this is the clearest tell:

```bash
uv run python dp-lookup-pro WORLI 947
```

| Output | Version |
| :--- | :--- |
| `"crz_status": "NO (Outside CRZ Buffer)"` | **old** (`main`) — this answer is wrong |
| `"crz_status": "YES (CRZ II)"` | **new** (`v3.7.0-hardening`) — correct |

---

## 🧯 Things that are *not* a fault

Before rolling back, check whether it is one of these:

| Symptom | Cause | What to do |
| :--- | :--- | :--- |
| `Could not reach the MCGM map server (ReadTimeout)` | MCGM rate-limits bursts of lookups | Wait ~30 s and retry. Space bulk lookups apart. |
| A lookup takes 13 s, another takes 5 s | MCGM's map-image endpoint is highly variable | Nothing to fix; it is ~95% of the runtime. |
| `Plot not found` | Village name must be one of 128 exact names | `BANDRA` is invalid — use `BANDRA-A`…`BANDRA-I`. See `START-HERE.md`. |
| A plot reports `CRZ: YES (CRZ II)` where it used to say `NO` | **The fix working.** The old answer was wrong. | Verify against the generated map image — CRZ II is printed on it. |
| Area shows as *derived* | MCGM has no approved area for that parcel | Expected. Check `plot_identity.area_source`. |
| First lookup after switching branches is slow | Cache formats differ between versions | Normal. |

---

## 🩺 Health check

To confirm an install is working, on either version:

```bash
uv run pytest -q                              # new version only: expect 47 passed
uv run python dp-lookup-pro BYCULLA 1605      # inland plot, should say CRZ: NO
uv run python dp-lookup-pro WORLI 947         # coastal plot, new version: CRZ: YES (CRZ II)
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
