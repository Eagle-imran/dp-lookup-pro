# 📋 CHANGELOG — `dp-lookup-pro`

All notable changes to this project. Newest first.

> **If something breaks after an update, see [ROLLBACK.md](ROLLBACK.md).**

---

## [3.7.0] — 2026-07-28

The first release to correct results rather than add features. Two lookups were
returning confidently wrong answers, and three separate paths could fail silently
while still producing an authoritative-looking PDF.

### 🔴 Corrected wrong results

**CRZ status was `NO` on every plot in Mumbai.**
The layer list held only *boundary lines* — High Tide Line, Low Tide Line, CRZ
Lines & Boundaries, Hazard Line. A point check at a plot's centre can never
touch a line, so the answer could only ever be `NO`. Replaced with the CRZ
*zone polygons* (layers 14, 1264, 1548). The sub-tier is now reported too, so
you get `YES (CRZ II)` rather than a bare `YES`.

| Plot | Before | After |
| :--- | :--- | :--- |
| WORLI 947 | NO | **YES (CRZ II)** |
| WORLI 886 | NO | **YES (CRZ II)** |
| BANDRA-A 409 | NO | **YES (CRZ II)** |
| BYCULLA 1605 | NO | NO ✓ *(correctly unchanged — inland)* |
| TARDEO 264 | NO | NO ✓ *(correctly unchanged — inland)* |
| **WORLI 733** | NO | **YES (CRZ II)** ✅ *(owner-verified against the actual plot)* |

⚠️ **Any PDF generated before this release understates CRZ status for coastal
plots.** Re-run anything you have issued to a client.

**Abutting roads were being missed.**
Two of the road lookups had never worked: they asked the server for roads
inside a shape, but those layers reject shape-based questions and reply with an
error that the tool read as "no roads found". Removed, and the remaining probes
now also sample along the plot's boundary edges, where roads actually run.

| Plot | Before | After |
| :--- | :--- | :--- |
| MOHILI 732 | `None` | **Road, 21.35 m** |
| WORLI 947 | B G KHER 18.30 M | unchanged ✓ |
| BYCULLA 1605 | DR ANANDRAO L NAIR RD 45.72 M | unchanged ✓ |

**Blank plot areas are now filled in.**
MCGM has no approved area on record for some parcels. The digitised boundary's
own area is used instead and clearly labelled — never presented as official.

| Plot | Before | After |
| :--- | :--- | :--- |
| MALABAR HILL 518 | *(blank)* | **2,450.16 m²** *(derived)* |
| TARDEO 264 | *(blank)* | **2,539.25 m²** *(derived)* |

New field `plot_identity.area_source` says which you got. The PDF prints
*"DERIVED from plot boundary — no approved area on MCGM record"*.

### 🛡️ Failures are no longer silent

Previously a network timeout produced `zone: Unknown`, `CRZ: NO`, no roads and
no neighbours — **and still wrote a full PDF, still logged to Excel, and cached
that result permanently.** The bad report was indistinguishable from a good one.

- A failed planning lookup now **stops the run** with a clear error instead of
  guessing.
- Partial failures appear in `metadata.warnings`, with `metadata.complete`
  saying whether the run was clean.
- **Incomplete results are never cached.**
- Server errors that arrive disguised as success (HTTP 200 carrying an error
  body) are now detected — this was the root cause of all three silent paths.
- Request timeout raised 10 s → 20 s; the old limit was routinely exceeded.

### 💾 Caching

- Expiry **24 hours → 30 days**, matched to how slowly this data actually moves
  (plot boundaries have not been edited since 2019-01-23).
- Cache hits **verify the files still exist**. Previously, deleting an output
  folder produced a confident success pointing at seven missing files.
- Every hit reports its age: `cached_at`, `cache_age_days`,
  `cache_expires_in_days`, plus a line on screen.
- Store moved to `<output_dir>/.cache_store.json` — it used to ignore your
  chosen output folder and always write to `./output`.
- **`--no-cache`** forces a fresh check.

### 🔐 Safety and correctness

- Village and CTS inputs are validated before being sent to the server, closing
  a query-injection hole.
- `&` and `<` in any name no longer corrupt the KML or crash PDF generation.

### 📦 Packaging and install

- `pip install -e .` now works, providing a `dp-lookup-pro` command that runs
  from any folder.
- Fixed a startup line that worked only on macOS — the tool previously could not
  run on Linux and could not run on Windows at all.
- Pillow minimum raised to 10.1.0; the map legend needs it.

### 🧪 Tests

47 offline tests added (`uv run pytest -q`) covering projection maths, tile
arithmetic, input validation, escaping, cache expiry, file verification and all
three vector exporters. There were none before.

### 📚 Documentation

- **`START-HERE.md`** — plain-English guide for non-technical users, including
  all 128 valid village names.
- **`APP_FLOW.html` / `APP_FLOW.json`** — system flow map, visual and
  machine-readable.
- **`LICENSE`** — proprietary, all rights reserved. The docs previously claimed
  MIT, which would have given the software away.
- Corrected every documented example: `BANDRA 100` does not exist, and `BANDRA`
  is not a valid village name at all.
- Corrected latency claims: measured **5–13 s** cold, not the ~800 ms claimed.

### ⏱️ Performance note

A single request — the DP map image — accounts for **~95% of a cold lookup**
(12.3 s of 13.0 s measured). Everything else finishes in under half a second.
The same plot re-ran at 5.2 s, so that endpoint is highly variable. This is
MCGM-side, not something the tool controls.

Cost per lookup: **₹0** — no paid APIs or keys. 25 requests, 228 KB down,
3.59 MB written to disk.

---

## [3.6.0] — 2026-07-28 (earlier)

- Native AutoCAD `.dxf` export with 11 pre-styled CAD layers.
- Query-specific bundle folders (`output/<village>_cts_<cts>/`).

## [3.5.0] and earlier

- Satellite view rebuilt on XYZ tile stitching after the previous export
  endpoint began returning HTTP 500.
- Single-batch concurrent request pipelining.
- 2-page PDF docket, HD DP map, GeoJSON and KML exports, Excel register.
