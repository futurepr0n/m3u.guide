# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Start application (sets up venv, installs deps, initializes DB, runs on port 4444)
./startup_app.sh

# Manual run
source venv/bin/activate && python3 app.py

# Docker (development mode, port 4444)
docker-compose -f compose-dev.yaml up

# Initialize database
python3 -c "from app import app; from models import db; app.app_context().push(); db.create_all()"
```

## Architecture

### Key Files
- **app.py** (~1100 lines): Flask app + all routes + `PlaylistManager` class
- **m3u_epg_editor.py**: Module imported by `app.py` as `editor` — provides `setup_custom_dns()`, `perform_get_with_backups()`, `get_random_user_agent()` for robust downloading
- **m3u-epg-editor-py3.py**: Legacy CLI script, still invoked as a subprocess by `/optimize-playlist`
- **m3u_analyzer_beefy.py**: Analyzer run during auto-analysis (`analyze_playlist_internal`)
- **m3u_analyzer_beefy-new.py**: Enhanced analyzer (VLC buttons, copy URL) — used by the manual `/analyze-playlist` endpoint
- **models.py**: SQLAlchemy models — `User → Playlist` (1:many), no Group/Channel DB models; editor uses M3U files directly
- **auth.py**: Blueprint for `/login`, `/register`, `/logout`

### Two Analyzer Scripts
The split is intentional: `m3u_analyzer_beefy.py` runs automatically during playlist creation (fast, basic). `m3u_analyzer_beefy-new.py` runs when the user manually clicks Analyze (adds VLC launchers, copy-URL buttons, series management). Both output to `analysis/` dir and write `command.json` with statistics + channel IDs.

### Download Pipeline
`download_file()` in `app.py` delegates to `editor.perform_get_with_backups()` with a random user-agent and fallback DNS (Cloudflare/Google/Quad9 via `editor.setup_custom_dns()`, called at import time). This is the fix for M3U download failures against restrictive IPTV providers.

### Optimize Flow
`/optimize-playlist` reads `playlist.m3u_editor_command` (built from `command.json` after analysis), extracts the `-g=` groups param, then calls `m3u-epg-editor-py3.py` as a subprocess with `file://` URIs pointing to the local M3U and EPG files. Outputs `optimized/cleaned.m3u8` and `optimized/cleaned.xml`.

### File Storage
```
static/playlists/{user_id}/{secure_filename(playlist_name)}/
├── tv.m3u / epg.xml          # Source files
├── analysis/                 # HTML reports + command.json
└── optimized/                # cleaned.m3u8, cleaned.xml
```

### Session & Auth
All routes check `session['user_id']`. File-serving routes additionally verify `session['user_id'] == user_id` from the URL to prevent cross-user access.

## Gotchas

- `secure_filename()` is applied to playlist names when resolving file paths but the raw name is stored in the DB — always use `secure_filename()` when building paths
- Template changes require hard refresh (`Cmd+Shift+R`) in browser due to caching
- The `m3u_editor_command` stored in the DB still references `m3u-epg-editor-py3.py` by name; `optimize_playlist()` rebuilds the actual command with fresh local paths at runtime
- IPTV streams don't play in browser — they work via VLC only; MP4/MKV files play natively
- Logs go to `logs/app.log` with rotating handler
