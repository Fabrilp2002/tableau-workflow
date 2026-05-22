# SDD — Tableau Workflow Assistant

> Short version. Full design doc lives at [`docs/full/SDD.md`](./docs/full/SDD.md).

## What this MCP does

A Tableau Cloud automation server exposed via MCP, plus a Claude skill that orchestrates it. Built around 4 workflows:

| # | Workflow | Status |
|---|---|---|
| 1 | **Refresh** datasources, monitor jobs | Phase 1 — implemented |
| 2 | **Clone + Remap** a workbook to a new datasource | Phase 2 — pending |
| 3 | **Bug fix** broken filters / wrong percentages | Phase 3 — pending |
| 4 | **Compose** a dashboard from charts in multiple workbooks | Phase 3 — pending |

## Architecture (1 paragraph)

`server.py` exposes ~25 MCP tools backed by `tableau_client.py` (TSC wrapper for REST + Metadata API), `workbook_parser.py` (lxml-based .twb inspector), `catalog.py` (local SQLite index of all workbooks for fast search), and `field_matcher.py` (fuzzy + sample-based matcher for clone+remap). Skill prompts in `skill/` guide Claude through each workflow.

## Tools (Phase 1)

- **Discovery**: `site_info`, `list_projects`, `list_workbooks`, `list_datasources`, `get_datasource_fields`
- **Inspection**: `download_workbook`, `download_datasource`, `parse_workbook`, `workbook_summary`
- **Refresh**: `refresh_datasource`, `check_refresh_job`, `refresh_and_wait`
- **Publish**: `publish_workbook`, `publish_datasource`, `create_extract_for_datasource`
- **Catalog**: `build_catalog`, `catalog_stats`, `search_catalog`, `list_indexed_workbooks`, `get_workbook_details`
- **Compare**: `compare_datasources`
- **Backup**: `backup_workbook` (requires `confirm=True`)

## Phase 2/3 pending tools

`swap_datasource`, `remap_fields`, `validate_workbook_xml`, `republish_workbook`, `clone_and_remap`, `diagnose_filters`, `set_filter_context`, `set_filter_scope`, `promote_filter_to_dashboard`, `update_calc_field`, `compose_dashboard`.

## Security posture

Path validation against allowed roots, zip slip protection, GraphQL injection escaping, PAT only via env, destructive ops require explicit `confirm=True`. See [`SECURITY.md`](./SECURITY.md) for the threat model.

## Key references in the full doc

- §5.5 — Filter bug taxonomy (10+ variants observed)
- §5.6 — Compose dashboard algorithm
- §6 — XML editing primitives
- §8 — Phase 2 workbook editor design
- §10.4 — Filter bug catalog with reproduction cases
