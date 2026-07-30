# 🏛️ Start Here — Mumbai DP Plot Reports, Just by Asking

**Ask your AI assistant about any Mumbai plot. Get a complete Development Plan report in seconds.**

You type this:

> *"Run DP lookup for Bandra-A CTS 409"*

You get back a folder with a client-ready PDF, an AutoCAD drawing, maps, and a Google Earth file.

No GIS software. No portal logins. No manual searching.

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

One request creates a folder containing **six files**:

| File | Who it's for | What you do with it |
| :--- | :--- | :--- |
| 📄 **PDF Report** | Your client | 2-page DP remark docket — email it, print it, attach it to a proposal |
| 📐 **AutoCAD `.dxf`** | Your architect | Opens in AutoCAD to scale, with the road, setback lines, neighbouring plots and a layer legend. Send them [docs/DXF-GUIDE.md](docs/DXF-GUIDE.md) with it. |
| 🗺️ **HD Zoning Map** | You | Zone, reservations and road widths at a glance |
| 📸 **Satellite View** | You | What's actually built on the ground today |
| 🌍 **Google Earth `.kml`** | Site visits | Double-click → flies you to the plot in 3D |
| 📊 **Excel Register** | Your records | Every plot you've ever looked up, in one running log |

Everything lands in a folder named after the plot, for example
`output/bandra_cts_100/`.

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

    Plot area         115.58 m²   (MCGM approved)
    Zone              R
    CRZ               YES (CRZ II)
    Abutting road     Bazar Road
    Adjoining plots   4

    Files            ./output/bandra-a_cts_409  (6 files)
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

---

## ⚠️ Important — read this

This tool reads MCGM's public map service and formats what it finds. Its output is **indicative only**.

It is **not** an official DP Remark, **not** a legal document, and **not**
certified by MCGM. Always obtain an official DP Remark from the Corporation
before making any legal, financial or development decision.

---

## 📜 Licence

Proprietary software. © 2026 Imran Patel. All rights reserved.

*Version 3.10.0 — see [docs/CHANGELOG.md](docs/CHANGELOG.md). If an update ever breaks
something, [docs/ROLLBACK.md](docs/ROLLBACK.md) explains how to go back.*

Free for personal evaluation and testing. Commercial use, redistribution and
modification are not permitted without written permission — see [LICENSE](LICENSE).

For commercial licensing, please get in touch.
