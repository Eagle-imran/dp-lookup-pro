# ⏪ ROLLBACK — How to go back if something breaks

> **Short version:** the update is now on `main` (merged 2026-07-29).
> To undo it, run **`git revert -m 1 9bc0f2e`**. Nothing is lost either way.

---

## 🗂️ The two versions you have

| Reference | Commit | What it is |
| :--- | :--- | :--- |
| **`main`** | `9bc0f2e` | **Current.** v3.10.0 — all fixes. Pushed to GitHub. |
| the merge | `9bc0f2e` | One commit containing the whole update — revert this to undo it all |
| pre-update `main` | `cb6df26` | The old version, still in history |
| **`v3.7.0-hardening`** | `55777f3` | The branch, kept as a safety net (local + GitHub) |

Nothing was deleted. Every old version is still in git history and can be
restored.

---

## ✅ Scenario 1 — "The new version misbehaves, put it back"

The whole update went in as one merge, so one command undoes all of it:

```bash
cd ~/Developer/dp-lookup-pro-IP
git revert -m 1 9bc0f2e
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
git checkout cb6df26      # detached view of the pre-update code
git checkout main         # back to current
```

> ⚠️ **Expect the first lookup after switching to be slow** (5–13 seconds
> instead of instant). Each version ignores the other's cache, so it refetches.
> That is normal, not a fault.

---

## ✅ Scenario 2 — "I want it gone from history entirely"

```bash
git reset --hard cb6df26
git push --force origin main
```

> ⚠️ **This is the destructive option.** `reset --hard` discards the work, and
> the force-push rewrites GitHub's history. The update is already published, so
> prefer Scenario 1's revert unless you are certain nobody has pulled it.
> The `v3.7.0-hardening` branch would still hold the work either way.

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
| `CRZ  YES (CRZ II)` | **current** (v3.10.0) — correct |
| `CRZ  NO (Outside CRZ Buffer)` | **old** — this answer is wrong for a coastal plot |

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
