# Setup — Quick (Windows + Claude Desktop)

> Full walkthrough with troubleshooting tables: [`docs/full/SETUP.md`](./docs/full/SETUP.md).

## TL;DR

1. **Python 3.10+** → `python --version`
2. **Tableau PAT** → Cloud → Avatar → My Account Settings → Personal Access Tokens → Create (name it, copy the secret immediately, it shows once)
3. **Install** → double-click `install.bat` (creates `.venv`, installs deps, copies `.env.example` → `.env`)
4. **Edit `.env`** with `TABLEAU_SERVER_URL`, `TABLEAU_SITE_NAME`, `TABLEAU_PAT_NAME`, `TABLEAU_PAT_VALUE`, `TABLEAU_LOCAL_FOLDER` (use `/` or `\\` in paths, not `\`)
5. **Verify** → `verify.bat` (smoke test against Cloud)
6. **Register MCP** in `%APPDATA%\Claude\claude_desktop_config.json`:
   ```json
   {"mcpServers": {"tableau-workflow": {"command": "C:\\path\\to\\tableau-workflow\\run-server.bat", "args": []}}}
   ```
7. **Install skill** → copy `skill/` contents to `%USERPROFILE%\.claude\skills\tableau-workflow\`
8. **Restart Claude Desktop completely** (tray → Quit)
9. **Smoke test** in chat: ask Claude to call `site_info`

## Quick fixes

| Symptom | Fix |
|---|---|
| `verify.bat` returns 401 | PAT expired or wrong — regenerate in Cloud, update `.env` |
| MCP red dot in Claude Desktop | Check `%APPDATA%\Claude\logs\` for the actual error |
| Skill not detected | Confirm Claude Desktop's skill directory — might be `%APPDATA%\Claude\skills\` on some builds |
| `python` not recognized | Re-install with "Add Python to PATH" checked |
| Catalog too slow | `build_catalog(project_id="...")` to scope to one project |

## OneDrive warning

If you clone into OneDrive/Dropbox, your `.env` (with the PAT secret) gets uploaded to that provider. Use a plain folder like `C:\Users\<you>\tableau-workflow\`.
