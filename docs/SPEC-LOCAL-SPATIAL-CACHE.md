# 🗄️ SPEC — Local Spatial Cache

**Status:** Ready to build
**Date:** 2026-07-30
**Supersedes:** `FEATURES_PLANNED.md` § 4.1 (Local Offline SQLite / DuckDB Spatial Database)
**Affects:** cache layer, `lookup_plot_pro`, neighbour detection

---

## 📌 In one line

Replace the flat JSON cache with a spatially indexed SQLite one, so parcel geometry
is fetched once and adjacency is **computed** instead of **guessed** — while every
planning answer stays live.

---

## 🔬 Measured facts this spec is built on

The original proposal was written against estimates. These are the numbers from the
live server (2026-07-30), and two of them change the plan.

| | Proposal assumed | Measured | How |
| :--- | :--- | :--- | :--- |
| Parcels in Mumbai | ~15,000 | **135,337** | `layer 13 /query?returnCountOnly=true` |
| Pre-baked file size | 18–25 MB | **~90 MB** (5 attrs + R-Tree)<br>**~126 MB** (all 33 fields) | 400 real WORLI parcels sampled |
| Geometry per parcel | — | median **189 B** WKB, mean **482 B** | same sample |
| Vertices per parcel | — | median **11**, mean **29.1**, max **4,996** | same sample |
| Bulk extraction | assumed hard | **easy** — `maxRecordCount: 50000`, `supportsPagination: true` | layer 13 metadata |

Layer 13 is `Global_Property_merge_v7`, 33 fields, carrying `CTS_CS_NO`, `VILLAGE`,
`WARD`, `TYPE`, `AREA_APP_SQ_MTRS` **and** geometry.

**The size cannot be reduced by simplifying geometry.** DXF dimensions are accurate
to 4.6 cm over 50 m and that is the product promise. Douglas-Peucker on a boundary
breaks the deliverable.

---

## 🧭 The governing rule

> **Geometry is cached. Planning status is always live.**

Layer 13 carries geometry and identity. It does **not** carry zone, reservation,
designation, DP modification, CRZ or metro buffer — those come from layers
`0, 46, 47, 192, 1550` and `14, 1264, 1548`.

That is a clean architectural seam, and it maps exactly onto what is safe to cache:

* **Geometry barely moves.** MCGM's digitisation of a parcel is stable for years.
* **Status is what changes, and what an architect acts on.** Reservations get
  amended; DP modifications get approved.

This codebase has already been burned by serving stale status: `read_cache_entry`
refuses undated entries specifically because pre-fix records held wrong CRZ answers
(`test_legacy_untimestamped_entries_are_treated_as_expired`). Baking status into a
shipped file with no expiry is the same mistake with a longer blast radius.

**A cached parcel must never shorten the planning path.** If geometry is a cache hit,
the identify calls still fire, every time.

---

## ✅ Scope — Phase 1 only

Build a spatial cache that **grows as the tool is used**. Ships at 0 MB, needs no
bulk extraction, and raises no redistribution question.

**In scope**

1. SQLite store with an R-Tree index, replacing `.cache_store.json`.
2. Parcel geometry cached on every successful lookup.
3. Cache hit skips the one *sequential* network request in the pipeline.
4. Adjoining parcels computed from the cache when coverage allows, with the method
   recorded in the output.
5. Migration from the existing JSON cache, and a documented rollback.

**Explicitly not in scope**

| Not building | Why |
| :--- | :--- |
| A pre-baked 126 MB city-wide database | 5× the proposal's size estimate; changes the install story for the non-technical audience. Revisit as an opt-in download (Phase 2). |
| SpatiaLite | A native library, contrary to the "simple install" goal. Not needed — see below. |
| City-wide feasibility search | A different product. Needs cached *status*, which this spec forbids. Phase 3. |
| Geometry simplification | Breaks the dimensional accuracy the DXF promises. |
| Offline generation of a full report | Without live status the PDF has no verdict. A confident-looking drawing missing its constraints is the most dangerous artefact this tool can emit. |

---

## 🧱 No new dependencies

Verified on this machine:

```
sqlite3 (stdlib)   R-Tree compiled in — verified, no extra dependency
shapely 2.1.2      already a dependency (setback offsets)
```

Confirm on the target machine rather than assuming — R-Tree is optional at SQLite
compile time, which is why the error-handling table below carries a fallback for it.

**R-Tree for bounding-box candidate filtering, shapely for exact predicates.** That
covers everything this spec needs. SpatiaLite is only worth revisiting if a query
appears that shapely genuinely cannot express.

---

## 🗃️ Schema

```sql
CREATE TABLE IF NOT EXISTS parcel (
    objectid      INTEGER PRIMARY KEY,
    cts_no        TEXT NOT NULL,
    village       TEXT NOT NULL,
    ward          TEXT,
    type          TEXT,
    area_app_sqm  REAL,              -- MCGM AREA_APP_SQ_MTRS; may be NULL
    geom          TEXT NOT NULL,     -- see geom_format
    geom_format   TEXT NOT NULL DEFAULT 'rings_json',
    centroid_lon  REAL NOT NULL,
    centroid_lat  REAL NOT NULL,
    fetched_at    REAL NOT NULL,     -- unix seconds; the snapshot date
    source        TEXT NOT NULL      -- 'live' | 'bulk'
);

CREATE UNIQUE INDEX IF NOT EXISTS parcel_key ON parcel(village, cts_no);

CREATE VIRTUAL TABLE IF NOT EXISTS parcel_bbox USING rtree(
    objectid, min_lon, max_lon, min_lat, max_lat
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- meta: schema_version, created_at
```

**`geom_format` exists from day one so the Phase 2 migration is free.** Phase 1
stores `rings_json` — WGS84 `[[[lon,lat], …], …]`, matching what `export_geojson`
and `export_dxf` already consume, and inspectable with `sqlite3` alone. Phase 2 bulk
loading should write `wkb` (roughly half the size); readers dispatch on the column.

**`fetched_at` is per row, not per file.** A cache assembled over months has rows of
different ages, and the age of *this* parcel is what matters.

---

## 🔌 API surface

```python
def spatial_cache_path(output_dir: str) -> str
def open_spatial_cache(output_dir: str) -> sqlite3.Connection      # creates schema if absent

def cache_parcel(conn, *, cts_no, village, rings, ward=None, type_=None,
                 area_app_sqm=None, objectid=None, source="live") -> None
def lookup_parcel(conn, village: str, cts_no: str,
                  max_age_seconds: Optional[float]) -> Optional[Dict[str, Any]]

def parcels_near(conn, lon: float, lat: float, radius_m: float) -> List[Dict[str, Any]]
def adjoining_parcels(conn, rings: list, village: str, cts_no: str,
                      tolerance_m: float = 0.5) -> Optional[List[Dict[str, Any]]]
```

`adjoining_parcels` returns `None` — not `[]` — when cache coverage is too thin to
trust. `[]` means "checked, genuinely none"; `None` means "cannot answer, fall back".
Conflating the two is how a plot silently loses its neighbours.

---

## 🔀 Flow changes in `lookup_plot_pro`

**Parcel fetch.** The parcel query is the single sequential request before the 24
concurrent ones, so a hit removes it from the critical path:

```
miss → query layer 13 (as today) → cache_parcel() → continue
hit  → skip the query, dispatch the identifies immediately
```

**Planning identifies — unchanged.** Always live. No cache path.

**Neighbours.** Today this fires 4 point-identify probes at fixed offsets — a guess
about where neighbours are, returning 2 at AMBIVALI 807 and 3 at WORLI 733 with no
way to know whether that is complete.

```
adjoining_parcels() returns a list → use it,   method = "spatial"
adjoining_parcels() returns None   → 4 probes, method = "probe"
```

**Record the method in the output.** `plot_identity.adjacency_method` in the JSON, and
a line in the DXF PLOT DATA panel. One result is exact and the other is an
approximation; a consumer must be able to tell which they were given.

### Adjacency algorithm

1. Bounding box of the subject rings, expanded by `tolerance_m`.
2. R-Tree query for candidate `objectid`s (cheap, no geometry parsed).
3. shapely `intersects` / `touches` against a `buffer(tolerance_m)` of the subject.
4. Exclude the subject's own `(village, cts_no)`.

**Coverage test (returns `None` if it fails):** at least one cached parcel other than
the subject within `radius = max(plot_width, plot_height) + 30 m`. An empty
neighbourhood means an empty cache, not an isolated plot.

The `0.5 m` tolerance accommodates digitisation gaps between adjacent parcels — MCGM's
boundaries do not always share vertices. **Tune it against known plots and record the
evidence; do not guess it.** WORLI 733 (3 known neighbours) and AMBIVALI 807 (2) are
the starting fixtures.

---

## ⏱️ TTL

Geometry and bundles expire on different clocks:

| Cached thing | TTL | Reason |
| :--- | :--- | :--- |
| Bundle result (existing) | 30 days (`DEFAULT_CACHE_TTL_SECONDS`) | Carries planning status. Unchanged. |
| Parcel geometry (new) | **180 days**, surfaced as `geometry_age_days` | Digitisation is stable; re-fetching it buys nothing. |

`--no-cache` must bypass **both**. A user reaching for it is asking for ground truth.

---

## 🔁 Migration and rollback

- On first run, create `.spatial_cache.sqlite` beside the existing
  `.cache_store.json` in `output_dir`. **Do not delete the JSON store.**
- Do not backfill from JSON: it holds results, not parcel geometry, and inventing
  rows from it would produce entries with no honest `fetched_at`.
- The JSON store keeps its current role for bundle results. This spec adds a store,
  it does not replace that one.
- **Rollback:** delete `.spatial_cache.sqlite`. The tool must run correctly with the
  file absent, unreadable, or corrupt — every code path degrades to today's live
  behaviour. Add this to `ROLLBACK.md` § Scenario 3 when the feature lands.

---

## 🚨 Error handling

| Condition | Behaviour |
| :--- | :--- |
| Cache file missing | Create it; continue live |
| Cache file corrupt / not a database | Warn to stderr, **rename to `.corrupt`**, recreate, continue live |
| `sqlite3` compiled without R-Tree | Fall back to a full-table bbox scan; warn once. Correct, just slower |
| Disk full / read-only output dir | Warn once, run entirely live. Never fail a lookup because a cache write failed |
| Cached rings fail to parse | Delete that row, re-fetch live |
| Cached geometry older than TTL | Treat as a miss |
| Concurrent processes | WAL mode; writes are `INSERT OR REPLACE`, so a race overwrites with equivalent data |

**A cache is an optimisation. No cache failure may change an answer or abort a run.**

---

## 🧪 Testing

All offline, no network, consistent with the existing 147 tests.

**Store**
- Schema creates cleanly; opening twice is idempotent.
- Round-trip: `cache_parcel` → `lookup_parcel` returns identical rings.
- `(village, cts_no)` uniqueness; re-caching updates rather than duplicating.
- Expiry: a row older than TTL is a miss; `max_age_seconds=None` disables expiry.
- Corrupt file is renamed and recreated, and the lookup still succeeds.
- A read-only directory does not raise.

**Spatial**
- `parcels_near` returns a parcel inside the radius and excludes one outside it.
- Adjacency finds a parcel sharing an edge.
- Adjacency finds a parcel separated by a 0.3 m digitisation gap (within tolerance).
- Adjacency **excludes** a parcel 5 m away.
- Adjacency excludes the subject itself.
- Empty cache → `None`, never `[]`.
- Result equals the known neighbour set for WORLI 733 (3) and AMBIVALI 807 (2),
  from fixtures.

**Integration**
- A cache hit produces byte-identical GeoJSON to a live fetch.
- A cache hit still performs the planning identifies (assert on a request spy) —
  **this is the test that protects the governing rule.**
- `--no-cache` bypasses the spatial cache.
- `adjacency_method` is present and correct in both branches.

---

## 📈 Performance — targets and honesty

| Metric | Today | Target |
| :--- | ---: | ---: |
| Parcel geometry fetch | ~300–800 ms | **< 5 ms** |
| Answer latency (warm geometry) | ~0.7 s typical | ~0.2–0.5 s |
| Adjacency | 4 network probes | < 10 ms, and **correct** |

**State the honest ceiling in the changelog when this ships.** The answer cannot
arrive before the planning identify, which measures **414 ms – 4,470 ms**. Removing a
~500 ms sequential hop from a ~900–5,000 ms answer is worth having and is not a 250×
speed-up. Measure three consecutive runs on WORLI 733, warm and cold, and publish
both — the same discipline as the v3.10.0 entry.

**The adjacency improvement is the real prize, and it is a correctness gain, not a
speed one.** Amalgamation studies are where a missed neighbour costs real money.

---

## 🔭 Later phases (not specified here)

**Phase 2 — opt-in per-village pre-bake.** A few hundred parcels each, ~1 MB, so
adjacency is complete in the villages someone actually works in without a 126 MB
payload. Bulk load writes `geom_format = 'wkb'`. Extraction is ~70 paginated requests
at 2,000/page; space them ~12 s apart.

**Phase 3 — city-wide feasibility search.** The genuine commercial unlock, and the one
that needs cached *status*. Requires a visible snapshot date and screening-only
framing: "find candidates" is a legitimate use of month-old data, "confirm a
reservation" is not.

---

## ❓ Open questions — resolve before Phase 2, not Phase 1

1. **Redistribution rights.** Bulk-extracting and shipping 135,337 MCGM parcel records
   inside a distributed file is a different act from proxying live queries, and this is
   a commercial product. Read MCGM's and the ArcGIS endpoint's terms before building on
   the assumption it is permitted. **Phase 1 sidesteps this entirely** — the cache is
   built by the user's own queries, on their own machine.
2. **Tolerance value.** `0.5 m` is a starting point, not a measurement. Calibrate
   against known-adjacent plots and record the result.
3. **Multi-ring parcels.** `export_dxf` already treats every ring as an outer boundary
   (`FEATURES_PLANNED.md` § Next up, item 4). Adjacency must not inherit that bug —
   decide explicitly how a parcel with an interior hole is indexed.

---

## 📐 Definition of done

- [ ] All tests above pass; suite stays green (147 + new).
- [ ] `ruff check .` clean.
- [ ] Deleting the cache file changes no output, only timing.
- [ ] A cache hit still fetches planning status live, proven by a test.
- [ ] `adjacency_method` visible in JSON and on the DXF sheet.
- [ ] Measured before/after published in `CHANGELOG.md`, with the ceiling stated.
- [ ] `ROLLBACK.md` § Scenario 3 gains a "disable the spatial cache" entry.
- [ ] `MEMORY.md` records the geometry-local / status-live rule.
