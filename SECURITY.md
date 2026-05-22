# Security — Short version

> Full threat model + audit history: [`docs/full/SECURITY.md`](./docs/full/SECURITY.md).

## Posture

- **PAT only via `.env`**, never in code/logs. `.gitignore` excludes `.env`.
- **Path validation**: all filesystem ops (download, parse, publish) reject paths outside `TABLEAU_LOCAL_FOLDER` + tempdir + `TABLEAU_EXTRA_ALLOWED_PATHS`.
- **Zip slip protection**: .twbx unpacking rejects entries whose resolved path escapes the unpack root.
- **GraphQL injection**: Metadata API queries escape user-controlled fields.
- **Destructive ops gated**: `backup_workbook` and (Phase 2+) publish tools require `confirm=True`; without it they return a preview.
- **Prompt injection awareness**: the skill instructs Claude to flag suspicious instructions found inside workbook captions/descriptions and stop.

## Audit history (2025)

1 HIGH and 3 MEDIUM findings identified and fixed:
- HIGH — zip slip in `_unzip_twbx` (fixed)
- MED — GraphQL injection in `get_datasource_fields` (fixed)
- MED — path traversal in `download_workbook` save_dir (fixed)
- MED — `backup_workbook` no confirmation (fixed)

## Recommended operation

- Clone the repo into a **non-cloud-synced** folder (not OneDrive/Dropbox) so `.env` doesn't leak.
- Generate a **least-privilege PAT** (Explorer is enough for refresh; Creator only if you need Metadata API).
- Rotate the PAT every 90 days; Tableau Cloud auto-expires unused PATs at 15 days.
- Set `TABLEAU_LOCAL_FOLDER` narrowly — only the directory where your .twb/.twbx live.
