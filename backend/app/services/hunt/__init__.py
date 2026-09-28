"""3x Job Hunt: a personalised, repeatable job-search pipeline.

Profile -> query generation -> discovery -> normalization -> freshness ->
location tiers -> experience / skill / semantic matching -> dedupe (already
done on ingest) -> apply-link quality -> ranking -> categorised shortlist.

Modules:
  defaults  -- seed values and loading the per-user HuntConfig
  signals   -- work mode, remote region, seniority, freshness detection
  queries   -- search-query variation generation
  semantic  -- local TF-IDF similarity and optional embedding similarity
  assess    -- the pure per-job assessment (no database access)
  pipeline  -- persistence, the full run, the board, and notifications
"""
