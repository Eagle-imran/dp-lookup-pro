# 🏛️ Start Here — Mumbai DP Plot Reports, Just by Asking

**Ask your AI assistant about any Mumbai plot. Get a complete Development Plan report in seconds.**

You type this:

> *"Run DP lookup for Bandra-A CTS 409"*

You get back a folder with a client-ready PDF, an AutoCAD drawing, maps, and a Google Earth file.

No GIS software. No portal logins. No manual searching.

Once the local database is built, you can also search all plots at once—for
example, residential sites above 2,000 m² without reservations—and compare
shortlisted sites side by side. See [Plot intelligence](docs/PLOT_INTELLIGENCE.md).

---

## 📋 What it tells you

For any City Survey (CTS/CS) plot in Mumbai, under the MCGM Development Plan 2034:

- **What zone is it?** — Residential, Commercial, Industrial
- **Is it reserved?** — Garden, school, hospital, road widening, or clear
- **Has the DP been modified?** — Any notification order affecting the plot
- **Is it near the coast?** — CRZ (Coastal Regulation Zone) restrictions
- **Is it near a Metro line?** — Metro rail influence buffer
- **What road does it face, and how wide?** — Road name and width in metres
- **What are the neighbouring plots?** — Adjoining CTS numbers and their areas

---

## 📦 What you get, every time

One request creates a folder containing **seven bundle artifacts**, plus a
shared Excel register at the output root:

| File | Who it's for | What you do with it |
| :--- | :--- | :--- |
| 📄 **PDF Report** | Your client | 2-page DP remark docket — email it, print it, attach it to a proposal |
| 🌐 **Interactive Map Dossier** | You & Client | Standalone interactive map in your browser with 1-click satellite toggle and developable envelope |
| 📐 **AutoCAD `.dxf`** | Your architect | Opens in AutoCAD to scale, with the road, setback lines, neighbouring plots and a layer legend. Send them [docs/DXF-GUIDE.md](docs/DXF-GUIDE.md) with it. |
| 🗺️ **HD Zoning Map** | You | Zone, reservations and road widths at a glance |
| 📸 **Satellite View** | You | What's actually built on the ground today |
| 🌐 **QGIS `.geojson`** | Your GIS team | Import the scale-accurate plot polygon into QGIS or ArcGIS |
| 🌍 **Google Earth `.kml`** | Site visits | Double-click → flies you to the plot in 3D |
| 📊 **Excel Register** *(shared)* | Your records | Every plot you've ever looked up, in one running log at `output/dp-lookups.xlsx` |

The seven bundle artifacts land in a folder named after the plot, for example
`output/bandra_cts_100/`; the shared Excel register stays at
`output/dp-lookups.xlsx`.

---

## ⚙️ One-time setup (about 5 minutes)

You only ever do this **once**. After that, you just talk to your AI.

### Step 1 — Install `uv`

`uv` is a small free tool that sets up everything else automatically.

**On Mac or Linux** — open Terminal and paste:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**On Windows** — open PowerShell and paste:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your terminal afterwards.

### Step 2 — Download the tool

**If you know git:**
```bash
git clone https://github.com/Eagle-imran/dp-lookup-pro.git
cd dp-lookup-pro
```

**If you don't:** open the GitHub page, click the green **Code** button →
**Download ZIP**, then unzip it somewhere easy to find like your Desktop.

### Step 3 — Set it up

Open a terminal **inside that folder** and run:

```bash
uv sync
```

> 💡 **How to open a terminal in the folder:**
> **Mac** — open the Terminal app, type `cd ` (with a space after it), then drag
> the folder from Finder into the Terminal window and press Enter.
> **Windows** — right-click inside the folder → *Open in Terminal*

### Step 4 — Check it works

```bash
uv run python dp-lookup-pro BANDRA-A 409
```

This looks up a real plot on Bazar Road, Bandra. Within a few seconds you should
see this:

```
  🟢 CLEAR (No Reservation)
  BANDRA-A  ·  CTS 409  ·  Ward H/W

    Plot area         115.58 m²   (MCGM recorded)
    Zone              R
    CRZ               YES (CRZ II)
    Abutting road     Bazar Road
    Adjoining plots   4

    Files            ./output/bandra-a_cts_409  (7 bundle files)
    Fetched in 7.4s
```

If you see that, you're done. ✅ Your files are in `output/bandra-a_cts_409/`
— open the PDF to see what a finished report looks like.

---

## 💬 How to use it (the easy way)

### First, get an AI assistant

If you don't already have one, **Claude Code** is the simplest. Install it once:

```bash
npm install -g @anthropic-ai/claude-code
```

Then, in the terminal you opened inside the `dp-lookup-pro` folder, type:

```bash
claude
```

That starts your assistant *inside* the tool's folder — which is what lets it
run the lookups for you. (**Cursor**, **Windsurf** and similar assistants work
too: just open the `dp-lookup-pro` folder in them.)

### Then just ask, in plain English

> *"Run DP lookup for Bandra-A CTS 409"*

> *"Check the DP remarks for Worli CTS 748A and give me the PDF"*

> *"What's the zoning for Malabar Hill CTS 16/738?"*

Your AI runs the tool, reads the result, and explains it to you in plain language — then tells you where your PDF and drawings are saved.

### Or use the terminal directly

```bash
uv run python dp-lookup-pro "<VILLAGE NAME>" "<CTS NUMBER>"
```

Examples:
```bash
uv run python dp-lookup-pro BANDRA-A 409
uv run python dp-lookup-pro WORLI 748A
uv run python dp-lookup-pro "MALABAR HILL" "16/738"
```

> ℹ️ Use `uv run python dp-lookup-pro` rather than `./dp-lookup-pro` — the
> longer form is the one that works identically on Mac, Windows and Linux.

---

## ❓ "Plot not found" — what to do

This is the most common hiccup, and it's almost always the **village name**.

**The village is not the neighbourhood name.** MCGM uses old revenue village
names from the cadastral survey, and they're matched *exactly*.

The classic trap: **`BANDRA` is not a valid village name.** Bandra is split into
`BANDRA-A` through `BANDRA-I` plus `BANDRA-EAST`. Likewise there's no plain
`KURLA` (it's `KURLA - 1` to `KURLA - 4`) and no `BHANDUP` (it's `BHANDUP-E` /
`BHANDUP-W`).

There are exactly **128 valid village names**. Use one of these:

<details>
<summary><b>👉 Click to see all 128 valid village names</b></summary>

```
AAKSE · AAREY · AKURLI · AMBIVALI · ANDHERI · ANIK · ASALPE · BANDIVALI
BANDRA-A · BANDRA-B · BANDRA-C · BANDRA-D · BANDRA-E · BANDRA-EAST
BANDRA-F · BANDRA-G · BANDRA-H · BANDRA-I · BAPNALA · BHANDUP-E · BHANDUP-W
BHULESHWAR · BORIVALI · BORLA · BRAMHANWADA · BYCULLA · CHAKALA · CHANDIVALI
CHARKOP · CHEMBUR · CHINCHAVALI · COLABA · DADAR-NAIGAON · DAHISAR · DARAVALI
DEONAR · DHARAVI · DINDOSHI · EKSAR · ERANGAL · FORT · GHATKOPAR
GHATKOPAR KIROL · GIRGAUM · GORAI · GOREGAON · GUNDAVALI · GUNDHGAON
HARIYALI-E · HARIYALI-W · ISMALIA · JUHU · KANDIVALI · KANHERI · KANJUR-E
KANJUR-W · KIROL · KLERABAD · KOLEKALYAN · KOLEKALYAN UNIVERSITY · KONDIVATE
KOPRI · KURAR · KURLA - 1 · KURLA - 2 · KURLA - 3 · KURLA - 4 · LOWER PAREL
MADH · MAGATHANE · MAHIM · MAHUL · MAJAS · MALABAR HILL · MALAD · MALAD-E
MALAD-NORTH · MALAD-SOUTH · MALVANI · MANDALE · MANDPESHWAR-M · MANDPESHWAR-N
MANDPESHWAR-S · MANDVI · MANKHURD · MANORI · MARAVALI · MAROL · MAROL MAROSHI
MARVE · MATUNGA · MAZAGAON · MOGRA · MOHILI · MULGAON · MULUND-E · MULUND-W
NAHUR · OSHIWARA · PAHADI EKSAR · PAHADI GOREGAON-E · PAHADI GOREGAON-W
PAREL-SEWERI · PARIGHIKARI · PASPOLI · POISAR · POWAI · PRAJAPUR
PRINCESS DOCK · SAAI · SAHAR · SAKI · SALT PAN · SHIMPAWALI · SION · TARDEO
TIRANDAZ · TULSI · TUNGWE · TURBHE · VALNAI · VERSOVA · VIKHROLI · VILE PARLE
VYARAVLI · WADHAVALI · WADHWAN · WORLI
```

</details>

> 💡 **Easiest option:** just ask your AI — *"which village is this plot in?"* —
> and paste the list above, or point it at this file.

**Ask the tool for the list:**

```bash
uv run python dp-lookup-pro --list-villages
```

And if you get the name wrong, it will suggest the right one.

**Where to find your plot's village name:**

- Your **Property Register Card (PRC)** or **7/12 extract** — it's printed on it
- Any **sale deed** or **title document** for the plot
- The plot's **CTS sheet**

**Also check the CTS number:**
- It's exact — `16/738` and `16-738` are different plots
- Suffixes matter — `748A` is not the same plot as `748`

---

## 🔄 Getting fresh data

Reports are saved and reused for **30 days**, so repeat lookups are instant.
Every cached result tells you how old it is:

```
[dp-lookup-pro] Serving cached report from 2026-07-28 18:06 (3.4 days old).
Use --no-cache for a fresh check.
```

If a plot matters right now — a transaction, a submission — force a fresh check:

```bash
uv run python dp-lookup-pro WORLI 947 --no-cache
```

A successful fresh lookup becomes the new cache entry. For ordinary feasibility
and repeated design work, leave caching enabled. Use `--no-cache` for a final
client issue, transaction, submission, suspected MCGM update, or scheduled
30-day refresh.

## 🗃️ Optional local source database

The tool can build one local SQLite file containing MCGM's parcel layer and the
52 planning layers used by the lookup. This makes repeated studies faster and
more repeatable, gives exact neighbouring plots, and keeps working when a
planning-layer request is temporarily unavailable. It is an audited snapshot,
not the 30-day report cache, and the generated database stays on your machine
(`data/*.sqlite` is ignored by Git).

Build and check it explicitly:

```bash
uv run dp-lookup-pro db parcels build
uv run dp-lookup-pro db parcels status
uv run dp-lookup-pro db parcels verify
uv run dp-lookup-pro db parcels activate

uv run dp-lookup-pro db planning build
uv run dp-lookup-pro db planning status
uv run dp-lookup-pro db planning verify
uv run dp-lookup-pro db planning activate
```

Each build downloads a complete official inventory in atomic batches and leaves
a new snapshot ready for review. If interrupted, rerun the same command to skip
already committed ObjectIDs; it resumes only when the source inventory still
matches. It refuses to publish an incomplete download. Complete parcel and
planning snapshots were built, live-compared, and activated on 2026-08-21.
Together they occupy about 1.0 GiB in the ignored local database. Ordinary CLI
lookups now use them first and fall back visibly to live MCGM when necessary.

For routine maintenance, check before downloading:

```bash
uv run dp-lookup-pro db health
uv run dp-lookup-pro db check-upstream
uv run dp-lookup-pro db check-upstream --json > docs/audits/upstream-check.json
```

`health` is local and read-only. `check-upstream` contacts MCGM but retrieves
only metadata, edit signals and ObjectID inventories; it does not retrieve
geometry. If a signal changed or could not be checked, build a new staged
snapshot, verify and diff it, and activate it only after review. Run this cheap
check monthly or quarterly, perform the checked refresh every six months, and
force one complete rebuild annually because upstream timestamps and unchanged
ObjectIDs cannot prove that the coordinates themselves stayed unchanged.

With an activated snapshot, the normal command is local-first:

```bash
uv run dp-lookup-pro lookup WORLI 733
# Explicit form recommended for agents and new scripts.

uv run dp-lookup-pro WORLI 733
# Historical short form remains supported.
uv run dp-lookup-pro WORLI 733 --source local --database data/mcgm-layer13.sqlite
uv run dp-lookup-pro WORLI 733 --source auto --database data/mcgm-layer13.sqlite
uv run dp-lookup-pro WORLI 733 --source live
```

`local` requires the active local parcel and planning snapshots. `auto` tries
each local snapshot first and falls back to live MCGM when it cannot answer. A
parcel snapshot older than 210 days remains usable with a warning; stale
planning falls back live in `auto`. `--source live` forces the existing live
path. `auto` is the CLI default and uses `data/mcgm-layer13.sqlite`; set
`DP_LOOKUP_DATABASE` or pass `--database` to override it. Parcel identity,
neighbours, zone, reservation, designation, DP modification, CRZ, Metro
influence and optional evidence are local-first. Road name/width probes, the DP
map image and satellite image remain live. The database is an audited copy of
official source data; it is not itself a legal authority.

To switch snapshots safely, use `db parcels diff`, `db parcels activate`, and
`db parcels rollback`. See the [local snapshot
specification](docs/SPEC-LOCAL-SPATIAL-CACHE.md) for the reliability checks and
the verified source counts.

### Add better documents later

If you receive a Property Card, certified CTS/Final Plot plan, measurement
record, licensed survey, or official DP Remarks plan, add it to the separate
source registry. It lives in the same SQLite file, but never overwrites the
original MCGM snapshots.

```bash
uv run dp-lookup-pro evidence add evidence/worli-733.json --actor imran
uv run dp-lookup-pro evidence verify 12 --reviewed-by imran
uv run dp-lookup-pro evidence recommend WORLI 733
uv run dp-lookup-pro evidence activate 12 --purpose geometry --activated-by imran --reason "accepted boundary evidence"
```

The order is register, verify, recommend, then explicitly activate for `area`,
`geometry`, or `planning`. This lets the tool use the best evidence for each
field while keeping disagreements visible. Every document is versioned,
checksummed and audited. Normal lookup uses only active selections, and a
source change makes the affected cached report or intelligence record stale.
See [Certified sources](docs/CERTIFIED_SOURCES.md) for the simple manifest
format and all commands.

## 🔎 Optional deeper planning evidence

The normal command uses the established fast `basic` lookup. For a broader
source-backed due-diligence register, request it explicitly:

```bash
uv run dp-lookup-pro COLABA 1/600 --evidence standard --no-cache --json
uv run dp-lookup-pro "VILE PARLE" 1449 --evidence full --no-cache --json
```

`full` mode checks more MCGM layers and can take noticeably longer. Its findings
are screening evidence, not an official DP Remark or an automatic FSI/buildable
area conclusion. See [Planning evidence](docs/PLANNING_EVIDENCE.md) and the
[ArcGIS layer audit](docs/ARCGIS_LAYER_AUDIT.md).

---

## ⚠️ Important — read this

This tool reads MCGM's public map service and formats what it finds. Its output is **indicative only**.

It is **not** an official DP Remark, **not** a legal document, and **not**
certified by MCGM. Always obtain an official DP Remark from the Corporation
before making any legal, financial or development decision.

---

## 📜 Licence

Proprietary software. © 2026 Imran Patel. All rights reserved.

*Version 3.14.0 — see [docs/CHANGELOG.md](docs/CHANGELOG.md). If an update ever breaks
something, [docs/ROLLBACK.md](docs/ROLLBACK.md) explains how to go back.*

Free for personal evaluation and testing. Commercial use, redistribution and
modification are not permitted without written permission — see [LICENSE](LICENSE).

For commercial licensing, please get in touch.
