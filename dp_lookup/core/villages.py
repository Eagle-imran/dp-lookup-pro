"""Village catalogue queries shared by the CLI and application services."""

import difflib
from typing import Any, List

from dp_lookup.core.constants import MCGM_VILLAGES


def suggest_villages(name: Any, limit: int = 8) -> List[str]:
    """Return the nearest valid MCGM village names for a user-supplied value."""
    query = str(name or "").strip().upper()
    if not query:
        return []
    hits = [village for village in MCGM_VILLAGES if village == query]
    hits += [village for village in MCGM_VILLAGES if village.startswith(query) and village not in hits]
    hits += [village for village in MCGM_VILLAGES if query in village and village not in hits]
    for village in difflib.get_close_matches(query, MCGM_VILLAGES, n=limit, cutoff=0.6):
        if village not in hits:
            hits.append(village)
    return hits[:limit]
