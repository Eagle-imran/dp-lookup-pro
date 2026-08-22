# Certified-source registry

The certified-source registry lets a plot gain better evidence over time. It
is a separate, additive registry in the same SQLite database as the MCGM
parcel and planning snapshots. It does not replace, edit, or reshape the
original MCGM records.

The simple workflow is:

```text
register → verify → recommend → explicitly activate
```

Activation is always per purpose: `area` (reported area), `geometry`
(preferred boundary), or `planning` (planning/remarks evidence). A certified
source is stronger evidence for its stated purpose, but is not by itself a
legal conclusion.

## Source lifecycle

```bash
dp-lookup-pro sources add evidence/worli-733.json \
  --database data/mcgm-layer13.sqlite --actor imran
dp-lookup-pro sources list --database data/mcgm-layer13.sqlite --village WORLI --cts 733
dp-lookup-pro sources verify 12 --database data/mcgm-layer13.sqlite \
  --reviewed-by imran --notes "Readable and matches the CTS identity"
dp-lookup-pro sources recommend WORLI 733 --database data/mcgm-layer13.sqlite
dp-lookup-pro sources activate 12 --purpose geometry \
  --database data/mcgm-layer13.sqlite --activated-by imran \
  --reason "Licensed survey is the best current boundary evidence"
dp-lookup-pro sources audit --database data/mcgm-layer13.sqlite
```

Other lifecycle commands are:

```bash
dp-lookup-pro sources show 12 --database data/mcgm-layer13.sqlite
dp-lookup-pro sources withdraw 12 --database data/mcgm-layer13.sqlite \
  --actor imran --reason "Superseded by a newer survey"
```

Every command accepts `--json`. Registration creates a new versioned record;
verification records who reviewed it; recommendation is deterministic and
does not activate anything; activation is explicit and audited; withdrawal
preserves the record and its history.

## Manifest format

The add command accepts either one source object or a version-one manifest.
Paths are resolved relative to the manifest file, and every file is stored with
a SHA-256 checksum.

```json
{
  "manifest_version": 1,
  "items": [
    {
      "village": "WORLI",
      "cts_no": "733",
      "source_type": "property-card",
      "file": "worli-733/property-card.pdf",
      "sha256": "<sha256 of the file>",
      "issue_date": "2025-04-16",
      "issuing_authority": "City Survey Office",
      "reference": "PC-12345",
      "recorded_area_sqm": 1317.74
    },
    {
      "village": "WORLI",
      "cts_no": "733",
      "source_type": "total-station-survey",
      "file": "worli-733/survey.dxf",
      "sha256": "<sha256 of the file>",
      "issuing_authority": "ABC Licensed Surveyors",
      "survey_date": "2026-08-18",
      "original_crs": 3857,
      "original_geometry": {"rings": [[[8106500, 2151700], [8106520, 2151700], [8106520, 2151710], [8106500, 2151710], [8106500, 2151700]]]}
    }
  ]
}
```

The original source document, metadata, checksum, reviewer history and
selection history are retained. A changed file creates a new version; it does
not overwrite the prior record. An identical checksum is idempotent.

## Recommendation and conflicts

Recommendations are field-specific. A total-station survey may be preferred
for `geometry`, a digitally signed Property Card for `area`, and an official
DP Remarks plan for `planning`. Recommendations consider source type,
verification state, document date, identity match and completeness.

If two valid sources have the same rank, the tool does not silently choose one.
It reports an equal-rank conflict and leaves the previous active selection
unchanged until a person explicitly activates the preferred record with a
reason.

## Effect on normal lookup

Normal lookup continues to use the active MCGM parcel and planning snapshots.
It applies a supplied source only when that source has been explicitly
activated for the relevant purpose. MCGM raw attributes and geometry remain
available as the baseline and are never rewritten by the registry.

An active `area` source changes the working area and an active `geometry`
source changes the working boundary used for deterministic overlays. An active
`planning` source is attached as stronger, traceable evidence in the result;
the tool does not invent or OCR statutory findings from the document, and it
does not silently replace the mapped DP analysis.

Adding, verifying, activating or withdrawing a source changes the authority
fingerprint for the affected plot. The report cache and plot-intelligence build
must therefore be treated as stale for that plot (or rebuilt) when an active
source changes.

The registry improves the evidence chain; it does not turn the product into an
official MCGM record or replace a licensed professional's review.
