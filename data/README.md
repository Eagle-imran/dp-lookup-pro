# Local operational data

This directory holds generated, machine-local MCGM parcel and planning
snapshots. Database files, manifests and ingestion checkpoints are intentionally
excluded from Git because they are large operational data, not application
source code.

Use the CLI to manage them:

```bash
dp-lookup-pro db health
dp-lookup-pro db parcels status
dp-lookup-pro db planning status
```

Do not edit SQLite files or manifests by hand. Snapshot activation and rollback
are explicit CLI operations, and certified-source enrichment is versioned
without overwriting the archived MCGM records.
