# 0004. Charts are declarative specs compiled to aggregate SQL

Status: accepted (Phase 4)

## Context

A chart over a 5-million-row dataset can't ship rows to the browser. Charts also have to
be safe to share and to filter from a dashboard. They should keep working when the user
renames things in the UI.

## Decision

A chart stores a validated `ChartSpec` (type, x, up to 4 measures, series, time grain,
filters, display options) and never stores SQL. `analytics/charts.py`:

- validates the spec against the source schema, with readable errors such as "'region'
  is text; the x-axis of a line chart must be temporal or numeric";
- compiles it to a single aggregate query, capped at `MAX_POINTS`;
- folds series beyond the 7 largest into "Other" (3 for scatter, where overlapping marks
  must stay distinguishable). NULL series values get their own "(null)" group;
- bins histograms in SQL with round widths;
- samples scatter plots deterministically with `reservoir(5000) REPEATABLE (7)`.

Generated SQL runs through the same sandbox as user SQL. The chart builder's "SQL" tab
shows exactly what ran.

## Consequences

- Dashboard filters are plain `Condition`s ANDed into each chart's WHERE clause, and
  conditions on columns a chart's source lacks are skipped.
- Very custom visuals need a saved query as the chart source. That query is re-validated
  by the guard and embedded as a subquery.
- Charts are drawn with Recharts. Colours come from CSS variables, so light and dark
  themes stay consistent. Every multi-series chart gets a legend and a table view.
