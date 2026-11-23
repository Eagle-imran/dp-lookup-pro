# Certified authority sources and plot intelligence records

**Date:** 2026-11-24
**Status:** Accepted
**Affects:** `dp_lookup/authority/selection.py`, `dp_lookup/application/authority_resolver.py`,
`dp_lookup/application/intelligence_services.py`, `dp_lookup/intelligence/store.py`

Moved from code comments; see [2026-11-24 no code comments](2026-11-24-no-code-comments.md).

## Authority selection

- `supersedes_id` points from the new replacement to the old record. It is
  not evidence that the new record is superseded. The old record is excluded
  by its lifecycle status, or by an explicit `superseded_by` marker in
  alternate registries.
- The record checksum is the final, deterministic tie-breaker. Ascending
  order is used only because it is stable; it does not mean one hash is more
  authoritative than another.
- In the resolved authority output, the standardized fields are the stable
  public shape. The `baseline`/working block is additive diagnostic data.

## Plot intelligence

- Queries without a build ID require a current active build. An explicit
  historical build ID skips that check so old builds stay available for
  audit.
- Each plot record keeps its policy/quality metadata and the deterministic
  source-reference order archived with it. The normalized index owns only
  attributes.
