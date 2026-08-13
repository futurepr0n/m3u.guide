from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, render_template, make_response
import os
import requests
import subprocess
import sys
import secrets
import hashlib
import logging
import threading
import uuid
from datetime import datetime, timedelta
from flask_session import Session
import shutil
from pathlib import Path
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from werkzeug.utils import secure_filename
from models import db, init_db, User, Playlist, IntegrationToken
from auth import auth
import urllib.parse
import re
import json
from collections import defaultdict
import m3u_epg_editor as editor
from jellyfin_export import generate_jellyfin_export, iter_m3u
from jellyfin_vod_export import generate_vod_fixture, _safe
from jellyfin_profiles import load_profiles, save_profile
from jellyfin_vod_catalog import generate_vod_catalog, read_catalog_page
from provider_mirrors import normalize_mirrors, normalize_origin, rewrite_provider_url
from provider_health import probe_xtream_provider
from credential_crypto import decrypt_password, store_password
from security_controls import rate_limit, redact_data, redact_secrets
from plugin_repository import PACKAGE_NAME, build_manifest
from validate_plugin_repository import validate as validate_plugin_repository

# Setup DNS for the whole app
editor.setup_custom_dns()

# ── Background job tracking ──────────────────────────────────────────────────
_jobs: dict = {}
_jobs_lock = threading.Lock()

def _job_set(job_id: str, step: str, status: str = None, **kw):
    with _jobs_lock:
        j = _jobs.get(job_id)
        if not j:
            return
        j['step'] = step
        j['steps'].append(step)
        if status:
            j['status'] = status
        j.update(kw)


# Load environment variables
load_dotenv()

# Configure base directories
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
PLUGIN_REPOSITORY_DIR = STATIC_DIR / 'plugin-repository'
TEMPLATES_DIR = BASE_DIR / 'templates'
LOG_DIR = BASE_DIR / 'logs'
SESSION_DIR = BASE_DIR / 'data' / 'sessions'

# Ensure directories exist
for directory in [STATIC_DIR, TEMPLATES_DIR, LOG_DIR, SESSION_DIR]:
    directory.mkdir(exist_ok=True, parents=True)

_plugin_repository_errors = validate_plugin_repository(PLUGIN_REPOSITORY_DIR)
if _plugin_repository_errors:
    raise RuntimeError(
        'Jellyfin plugin repository validation failed: '
        + '; '.join(_plugin_repository_errors)
    )

class PlaylistManager:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.static_playlists_dir = self.base_dir / 'static' / 'playlists'
        self.static_playlists_dir.mkdir(exist_ok=True, parents=True)

    def get_user_playlists(self, user_id):
        """Retrieve all playlists for a given user from the database."""
        return Playlist.query.filter_by(user_id=user_id).all()

    def get_user_directory(self, user_id):
        user_dir = self.static_playlists_dir / str(user_id)
        user_dir.mkdir(exist_ok=True)
        return user_dir

    def get_playlist_path(self, user_id, playlist_name):
        return self.get_user_directory(user_id) / secure_filename(playlist_name)

    def add_playlist(self, user_id, playlist_data):
        try:
            # Create playlist directory in static folder
            playlist_dir = self.get_playlist_path(user_id, playlist_data['name'])
            playlist_dir.mkdir(exist_ok=True)

            playlist = Playlist(
                name=playlist_data['name'],
                source=playlist_data['source'],
                user_id=user_id,
                details=playlist_data.get('details', {}),
                last_sync=datetime.utcnow()
            )
            db.session.add(playlist)
            db.session.commit()
            return True
        except Exception as e:
            app.logger.error(f"Error adding playlist: {str(e)}")
            db.session.rollback()
            raise

    def delete_playlist(self, user_id, playlist_name):
        try:
            playlist = Playlist.query.filter_by(
                user_id=user_id,
                name=playlist_name
            ).first()

            if not playlist:
                return False, "Playlist not found"

            playlist_directory = self.get_playlist_path(user_id, playlist_name)
            if playlist_directory.exists():
                try:
                    shutil.rmtree(playlist_directory)
                except Exception as e:
                    return False, f"Failed to delete playlist directory: {str(e)}"

            db.session.delete(playlist)
            db.session.commit()
            return True, "Playlist deleted successfully"

        except Exception as e:
            app.logger.error(f"Error deleting playlist: {str(e)}")
            db.session.rollback()
            return False, str(e)

# Initialize Flask app
app = Flask(__name__, 
           static_folder=str(STATIC_DIR),
           template_folder=str(TEMPLATES_DIR))

# Configure app
app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32)),
    SESSION_TYPE='filesystem',
    # Never use the system-wide temporary directory here. Flask-Session may
    # inspect files in this directory during cleanup, which can make a login
    # appear to hang on a busy development machine.
    SESSION_FILE_DIR=str(SESSION_DIR),
    SESSION_PERMANENT=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    MAX_CONTENT_LENGTH=300 * 1024 * 1024,  # 100MB max file size
    SQLALCHEMY_DATABASE_URI='sqlite:///' + str(BASE_DIR / 'app.db'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SEND_FILE_MAX_AGE_DEFAULT=0
)

# Initialize extensions
Session(app)
init_db(app)

# Ensure stream_token column exists and backfill any users missing one
with app.app_context():
    from sqlalchemy import text
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN stream_token VARCHAR(32)'))
        db.session.commit()
    except Exception:
        pass  # Column already exists
    for u in User.query.all():
        if not u.stream_token:
            u.stream_token = secrets.token_hex(16)
    db.session.commit()

    # One-way migration: encrypt legacy provider passwords before serving.
    for playlist in Playlist.query.all():
        details = dict(playlist.details or {})
        if details.get('password'):
            store_password(details, str(details['password']))
            playlist.details = details
    db.session.commit()

# Register blueprints
app.register_blueprint(auth, url_prefix='/auth')


# Initialize PlaylistManager
playlist_manager = PlaylistManager(BASE_DIR)

# Configure logging
class SecretRedactionFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact_secrets(record.msg)
        if record.args:
            record.args = tuple(redact_secrets(item) for item in record.args) if isinstance(record.args, tuple) else redact_secrets(record.args)
        return True


if not app.debug:
    file_handler = RotatingFileHandler(
        LOG_DIR / 'app.log',
        maxBytes=10240,
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Application startup')

for handler in app.logger.handlers:
    handler.addFilter(SecretRedactionFilter())
for handler in logging.getLogger('werkzeug').handlers:
    handler.addFilter(SecretRedactionFilter())


@app.after_request
def redact_json_responses(response):
    """Prevent legacy and future JSON errors from serializing secrets."""
    if response.is_json and response.status_code >= 400:
        payload = response.get_json(silent=True)
        if payload is not None:
            response.set_data(json.dumps(redact_data(payload), ensure_ascii=False))
            response.content_type = 'application/json'
    return response

@app.route('/')
def serve_index():
    if 'user_id' in session:
        return render_template('index.html')
    return redirect(url_for('auth.login'))

@app.route('/get-playlists')
def get_playlists():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403
    
    from models import User
    uid = session['user_id']
    user = User.query.get(uid)
    playlists = playlist_manager.get_user_playlists(uid)
    token = user.stream_token
    playlist_list = []
    for p in playlists:
        safe_name = secure_filename(p.name)
        base_path = os.path.join(app.static_folder, 'playlists', str(uid), safe_name)
        stream_prefix = f'/stream/{token}/{safe_name}'
        jellyfin_path = os.path.join(base_path, 'exports', 'jellyfin', 'default')
        jellyfin_prefix = f'{stream_prefix}/jellyfin'
        playlist_list.append({
            'name': p.name,
            'source': p.source,
            'total_channels': p.total_channels,
            'total_epg_matches': p.total_epg_matches,
            'total_movies': p.total_movies,
            'total_series': p.total_series,
            'total_unmatched': p.total_unmatched,
            'm3u_editor_command': p.m3u_editor_command,
            'last_sync': p.last_sync.isoformat() if p.last_sync else None,
            'auto_sync': p.auto_sync,
            'has_analysis': os.path.exists(os.path.join(base_path, 'analysis', 'content_analysis_matched.html')),
            'm3u_url': f'{stream_prefix}/tv.m3u',
            'epg_url': f'{stream_prefix}/epg.xml' if os.path.exists(os.path.join(base_path, 'epg.xml')) else None,
            'edited_m3u_url': f'{stream_prefix}/tv_edited.m3u' if os.path.exists(os.path.join(base_path, 'tv_edited.m3u')) else None,
            'jellyfin_m3u_url': f'{jellyfin_prefix}/live.m3u8' if os.path.exists(os.path.join(jellyfin_path, 'live.m3u8')) else None,
            'jellyfin_epg_url': f'{jellyfin_prefix}/epg.xml' if os.path.exists(os.path.join(jellyfin_path, 'epg.xml')) else None,
            'jellyfin_manifest_url': f'{jellyfin_prefix}/manifest.json' if os.path.exists(os.path.join(jellyfin_path, 'manifest.json')) else None,
        })
    return jsonify({
        'user_id': uid,
        'playlists': playlist_list
    })

def _integration_auth():
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer '):
        return None
    raw_token = authorization[7:].strip()
    if not raw_token:
        return None
    token = IntegrationToken.query.filter_by(
        token_hash=IntegrationToken.digest(raw_token), revoked_at=None
    ).first()
    if token:
        token.last_used_at = datetime.utcnow()
        db.session.commit()
    return token

@app.route('/api/jellyfin/auth', methods=['POST'])
def jellyfin_authenticate():
    """Exchange m3u.guide credentials for a revocable Jellyfin token."""
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    allowed, retry_after = rate_limit(f'jellyfin-auth:{request.remote_addr}:{username.casefold()}', 5, 300)
    if not allowed:
        response = jsonify({'error': 'Too many authentication attempts'})
        response.status_code = 429
        response.headers['Retry-After'] = str(retry_after)
        return response
    password = str(data.get('password', ''))
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid username or password'}), 401
    record, raw_token = IntegrationToken.issue(
        user, str(data.get('device_name', 'Jellyfin'))
    )
    return jsonify({
        'access_token': raw_token,
        'token_type': 'Bearer',
        'token_id': record.id,
        'username': user.username,
    })

@app.route('/api/jellyfin/account')
def jellyfin_account():
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlists = []
    for playlist in Playlist.query.filter_by(user_id=token.user_id).order_by(Playlist.name).all():
        playlist_dir = playlist_manager.get_playlist_path(token.user_id, playlist.name)
        export_root = playlist_dir / 'exports' / 'jellyfin'
        playlists.append({
            'name': playlist.name,
            'source': playlist.source,
            'profiles': list(load_profiles(playlist_dir)),
            'export_ready': (export_root / 'default' / 'manifest.json').exists(),
            'vod_ready': (export_root / 'vod-fixture.zip').exists(),
        })
    return jsonify({'playlists': playlists})

@app.route('/api/jellyfin/playlists/<path:playlist_name>/export', methods=['POST'])
def jellyfin_api_export(playlist_name):
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    playlist_path = playlist_manager.get_playlist_path(token.user_id, playlist.name)
    requested_profile = str((request.get_json(silent=True) or {}).get('profile', 'default'))
    profiles = load_profiles(playlist_path)
    if requested_profile not in profiles:
        return jsonify({'error': 'Export profile not found'}), 404
    profile = profiles[requested_profile]
    details = dict(playlist.details or {})
    source = (playlist_path / 'tv_edited.m3u') if (playlist_path / 'tv_edited.m3u').exists() else (playlist_path / 'tv.m3u')
    manifest = generate_jellyfin_export(
        playlist_path,
        profile=requested_profile,
        group_prefixes=tuple(profile.get('live_group_prefixes', [])),
        stream_base=details.get('stream_base'),
        active_mirror=details.get('active_mirror'),
    )
    vod = generate_vod_catalog(
        source,
        playlist_path / 'exports' / 'jellyfin' / requested_profile,
        profile,
        overrides_path=playlist_path / 'vod-overrides.json',
        stream_base=details.get('stream_base'),
        active_mirror=details.get('active_mirror'),
    )
    manifest['vod'] = vod
    return jsonify(manifest)

@app.route('/api/jellyfin/playlists/<path:playlist_name>/profiles')
def jellyfin_api_profiles(playlist_name):
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    return jsonify({'profiles': list(load_profiles(playlist_manager.get_playlist_path(token.user_id, playlist.name)).values())})

@app.route('/api/jellyfin/playlists/<path:playlist_name>/groups')
def jellyfin_api_groups(playlist_name):
    """Return selectable source groups and counts for each content kind."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    playlist_path = playlist_manager.get_playlist_path(token.user_id, playlist.name)
    source = (playlist_path / 'tv_edited.m3u') if (playlist_path / 'tv_edited.m3u').exists() else (playlist_path / 'tv.m3u')
    if not source.exists():
        return jsonify({'error': 'Playlist source file not found'}), 404

    source_stat = source.stat()
    cache_path = playlist_path / 'jellyfin_groups.json'
    signature = {'size': source_stat.st_size, 'mtime_ns': source_stat.st_mtime_ns}
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            if cached.get('source') == signature:
                return jsonify(cached['groups'])
        except (OSError, ValueError, KeyError):
            pass

    counts = {'live': defaultdict(int), 'movie': defaultdict(int), 'series': defaultdict(int)}
    for entry in iter_m3u(source):
        group = entry.attributes.get('group-title', '').strip() or 'Uncategorized'
        counts[entry.content_kind][group] += 1
    raw_result = {
        kind: [
            {'name': name, 'count': count}
            for name, count in sorted(groups.items(), key=lambda item: item[0].casefold())
        ]
        for kind, groups in counts.items()
    }
    cache_path.write_text(
        json.dumps({'source': signature, 'groups': raw_result}, ensure_ascii=False),
        encoding='utf-8',
    )
    return jsonify(raw_result)


@app.route('/api/jellyfin/playlists/<path:playlist_name>/provider', methods=['GET', 'PUT'])
def jellyfin_api_provider(playlist_name):
    """Manage provider origins without exposing stored Xtream credentials."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    details = dict(playlist.details or {})
    source_origin = details.get('stream_base') or details.get('server')
    if not source_origin:
        source_path = playlist_manager.get_playlist_path(token.user_id, playlist.name) / 'tv.m3u'
        source_origin = detect_stream_base(source_path)
    if request.method == 'PUT':
        try:
            payload = request.get_json(silent=True) or {}
            mirrors = normalize_mirrors(payload.get('mirrors', []))
            active = normalize_origin(payload.get('active_mirror'))
            source_origin = normalize_origin(source_origin)
            allowed = {item.casefold() for item in mirrors}
            if source_origin:
                allowed.add(source_origin.casefold())
            if active and active.casefold() not in allowed:
                raise ValueError('Active provider must be the canonical source or an ordered mirror')
            details['stream_base'] = source_origin
            details['mirrors'] = mirrors
            details['active_mirror'] = active
            if 'user_agent' in payload:
                details['user_agent'] = str(payload['user_agent']).strip()[:256]
            playlist.details = details
            db.session.commit()
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
    return jsonify({
        'source_origin': source_origin,
        'mirrors': details.get('mirrors', []),
        'active_mirror': details.get('active_mirror'),
        'effective_origin': details.get('active_mirror') or source_origin,
        'user_agent': details.get('user_agent') or 'VLC/3.0.20 LibVLC/3.0.20',
    })


def _load_vod_overrides(playlist_path):
    path = playlist_path / 'vod-overrides.json'
    if not path.exists():
        return {'version': 1, 'series_aliases': {}, 'items': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    data.setdefault('version', 1)
    data.setdefault('series_aliases', {})
    data.setdefault('items', {})
    return data


@app.route('/api/jellyfin/playlists/<path:playlist_name>/profiles/<string:profile_name>/vod/diagnostics')
def jellyfin_api_vod_diagnostics(playlist_name, profile_name):
    """Return paginated parse failures with stable IDs and saved corrections."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    try:
        cursor = max(0, int(request.args.get('cursor', '0')))
        limit = min(500, max(1, int(request.args.get('limit', '100'))))
    except ValueError:
        return jsonify({'error': 'cursor and limit must be integers'}), 400
    playlist_path = playlist_manager.get_playlist_path(token.user_id, playlist.name)
    diagnostics = playlist_path / 'exports' / 'jellyfin' / profile_name / 'vod.parse-diagnostics.jsonl'
    if not diagnostics.exists():
        return jsonify({'error': 'Parse diagnostics not found; generate the export first'}), 404
    records, next_cursor = read_catalog_page(diagnostics, cursor, limit)
    overrides = _load_vod_overrides(playlist_path).get('items', {})
    for record in records:
        record['override'] = overrides.get(record['id'])
    manifest_path = diagnostics.parent / 'vod.manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    return jsonify({'items': records, 'next_cursor': next_cursor, 'counts': manifest.get('counts', {})})


@app.route('/api/jellyfin/playlists/<path:playlist_name>/vod/overrides/<string:item_id>', methods=['PUT', 'DELETE'])
def jellyfin_api_vod_override(playlist_name, item_id):
    """Persist a correction keyed by the stable provider source ID."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    if not re.fullmatch(r'[a-f0-9]{24}', item_id):
        return jsonify({'error': 'Invalid stable item ID'}), 400
    playlist_path = playlist_manager.get_playlist_path(token.user_id, playlist.name)
    data = _load_vod_overrides(playlist_path)
    if request.method == 'DELETE':
        data['items'].pop(item_id, None)
    else:
        payload = request.get_json(silent=True) or {}
        try:
            correction = {
                'series': str(payload['series']).strip(),
                'season': int(payload.get('season', 1)),
                'episode': int(payload['episode']),
                'episode_title': str(payload.get('episode_title') or '').strip(),
            }
            if not correction['series'] or correction['season'] < 0 or correction['episode'] < 1:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return jsonify({'error': 'Series, non-negative season, and positive episode are required'}), 400
        data['items'][item_id] = correction
    path = playlist_path / 'vod-overrides.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)
    return jsonify({'id': item_id, 'override': data['items'].get(item_id)})


@app.route('/api/jellyfin/playlists/<path:playlist_name>/vod/overrides/<string:item_id>/preview', methods=['POST'])
def jellyfin_api_vod_override_preview(playlist_name, item_id):
    """Preview the Jellyfin path and NFO fields for a correction."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    payload = request.get_json(silent=True) or {}
    try:
        series = str(payload['series']).strip()
        season = int(payload.get('season', 1))
        episode = int(payload['episode'])
        title = str(payload.get('episode_title') or f'Episode {episode}').strip()
        if not series or season < 0 or episode < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'Series, non-negative season, and positive episode are required'}), 400
    series_id = hashlib.sha256(series.casefold().encode('utf-8')).hexdigest()[:24]
    show = f'Shows/{_safe(series)} [m3u-{series_id}]'
    stem = f'S{season:02d}E{episode:03d} [m3u-{item_id}]'
    return jsonify({
        'relative_path': f'{show}/Season {season:02d}/{stem}.strm',
        'nfo': {'title': title, 'showtitle': series, 'season': season, 'episode': episode, 'uniqueid': item_id},
    })


@app.route('/api/jellyfin/playlists/<path:playlist_name>/provider/health', methods=['POST'])
def jellyfin_api_provider_health(playlist_name):
    """Run credential-safe, independent provider endpoint checks."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    allowed, retry_after = rate_limit(f'provider-health:{token.id}', 10, 60)
    if not allowed:
        response = jsonify({'error': 'Provider health check rate limit exceeded'})
        response.status_code = 429
        response.headers['Retry-After'] = str(retry_after)
        return response
    details = dict(playlist.details or {})
    username = details.get('username')
    password = decrypt_password(details)
    origin = details.get('active_mirror') or details.get('stream_base') or details.get('server')
    if not all([origin, username, password]):
        return jsonify({'error': 'Provider origin or stored Xtream credentials are incomplete'}), 400
    try:
        origin = normalize_origin(origin)
        source = playlist_manager.get_playlist_path(token.user_id, playlist.name) / 'tv.m3u'
        media_url = None
        if source.exists():
            first = next(iter_m3u(source), None)
            if first:
                media_url = rewrite_provider_url(first.url, details.get('stream_base'), origin)
        result = probe_xtream_provider(
            origin,
            username,
            password,
            user_agent=details.get('user_agent') or 'VLC/3.0.20 LibVLC/3.0.20',
            media_url=media_url,
        )
        return jsonify(result)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

@app.route('/api/jellyfin/playlists/<path:playlist_name>/profiles/<string:profile_name>', methods=['PUT'])
def jellyfin_api_save_profile(playlist_name, profile_name):
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    try:
        profile = save_profile(
            playlist_manager.get_playlist_path(token.user_id, playlist.name),
            profile_name,
            request.get_json(silent=True) or {},
        )
        return jsonify(profile)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

@app.route('/api/jellyfin/playlists/<path:playlist_name>/profiles/<string:profile_name>/vod')
def jellyfin_api_vod_page(playlist_name, profile_name):
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    try:
        cursor = max(0, int(request.args.get('cursor', '0')))
        limit = min(1000, max(1, int(request.args.get('limit', '500'))))
    except ValueError:
        return jsonify({'error': 'cursor and limit must be integers'}), 400
    export_path = playlist_manager.get_playlist_path(token.user_id, playlist.name) / 'exports' / 'jellyfin' / profile_name
    catalog = export_path / 'vod.catalog.jsonl'
    manifest_path = export_path / 'vod.manifest.json'
    if not catalog.exists():
        return jsonify({'error': 'VOD catalog not found; generate the export first'}), 404
    if not manifest_path.exists():
        return jsonify({'error': 'VOD manifest not found; generate the export first'}), 404
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    revision = manifest.get('revision', '')
    expected_revision = request.args.get('revision')
    if expected_revision and expected_revision != revision:
        return jsonify({
            'error': 'VOD catalog revision changed; restart synchronization',
            'revision': revision,
        }), 409
    records, next_cursor = read_catalog_page(catalog, cursor, limit)
    return jsonify({'items': records, 'next_cursor': next_cursor, 'revision': revision})

@app.route('/api/jellyfin/playlists/<path:playlist_name>/artifacts/<string:filename>')
def jellyfin_api_artifact(playlist_name, filename):
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    allowed = {'live.m3u8', 'epg.xml', 'manifest.json', 'validation.json', 'vod-fixture.zip'}
    if filename not in allowed:
        return jsonify({'error': 'Invalid artifact'}), 400
    playlist = Playlist.query.filter_by(user_id=token.user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404
    profile_name = request.args.get('profile', 'default')
    root = playlist_manager.get_playlist_path(token.user_id, playlist.name) / 'exports' / 'jellyfin'
    artifact_dir = root if filename == 'vod-fixture.zip' else root / profile_name
    if not (artifact_dir / filename).exists():
        return jsonify({'error': 'Artifact not found; generate the export first'}), 404
    return send_from_directory(artifact_dir, filename)

@app.route('/api/jellyfin/token', methods=['DELETE'])
def jellyfin_revoke_token():
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    token.revoked_at = datetime.utcnow()
    db.session.commit()

    return ('', 204)


@app.route('/api/jellyfin/tokens')
def jellyfin_tokens():
    """List integration token metadata without returning token material."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    records = IntegrationToken.query.filter_by(user_id=token.user_id).order_by(IntegrationToken.created_at.desc()).all()
    return jsonify({'tokens': [{
        'id': item.id, 'device_name': item.name, 'token_prefix': item.token_prefix,
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'last_used_at': item.last_used_at.isoformat() if item.last_used_at else None,
        'revoked_at': item.revoked_at.isoformat() if item.revoked_at else None,
        'current': item.id == token.id,
    } for item in records]})


@app.route('/api/jellyfin/tokens/<int:token_id>', methods=['DELETE'])
def jellyfin_revoke_token_by_id(token_id):
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    target = IntegrationToken.query.filter_by(id=token_id, user_id=token.user_id).first()
    if not target:
        return jsonify({'error': 'Token not found'}), 404
    target.revoked_at = datetime.utcnow()
    db.session.commit()
    return ('', 204)


@app.route('/api/jellyfin/token/rotate', methods=['POST'])
def jellyfin_rotate_token():
    """Revoke the current token and issue a replacement for the same device."""
    token = _integration_auth()
    if not token:
        return jsonify({'error': 'Unauthorized'}), 401
    user = User.query.get(token.user_id)
    token.revoked_at = datetime.utcnow()
    record, raw_token = IntegrationToken.issue(user, token.name)
    return jsonify({'access_token': raw_token, 'token_id': record.id, 'token_type': 'Bearer'})

def _bg_process_playlist(app_ctx, job_id, user_id, name, source, form_data, files_data, host_url):
    with app_ctx:
        def prog(msg):
            _job_set(job_id, msg)
        try:
            playlist_dir = playlist_manager.get_playlist_path(user_id, name)
            playlist_dir.mkdir(parents=True, exist_ok=True)
            app.logger.info(f"Created directory: {playlist_dir}")
            m3u_path = playlist_dir / 'tv.m3u'
            epg_path = playlist_dir / 'epg.xml'
            playlist_data = {'name': name, 'source': source, 'details': {}}

            prog('Starting…')
            if source == 'API Line':
                prog('Downloading M3U from API Line…')
                success = process_api_line(form_data, m3u_path, epg_path, playlist_data['details'])
            elif source == 'M3U Url':
                prog('Downloading M3U from URL…')
                success = process_m3u_url(form_data, m3u_path, epg_path, playlist_data['details'])
            elif source == 'M3U File':
                prog('Processing uploaded M3U file…')
                success = process_m3u_file(files_data, m3u_path, epg_path, playlist_data['details'])
            elif source == 'Xtream API':
                success = process_xtream_api(form_data, m3u_path, epg_path, playlist_data['details'],
                                              host_url=host_url, progress_cb=prog)
            else:
                _job_set(job_id, f'Unknown source: {source}', 'error', error=f'Invalid source type: {source}')
                return

            if not success:
                _job_set(job_id, 'Processing failed — check credentials / server URL', 'error',
                         error='Failed to fetch playlist from provider')
                return

            prog('Saving to library…')
            playlist_manager.add_playlist(user_id, playlist_data)

            prog('Running content analysis…')
            try:
                analyze_playlist_internal(user_id, name)
                _job_set(job_id, 'Complete!', 'complete', analyzed=True)
            except Exception as ae:
                app.logger.error(f"Analysis error: {ae}")
                _job_set(job_id, 'Added (analysis skipped)', 'complete', analyzed=False)

        except Exception as e:
            app.logger.error(f"Background processing error: {e}")
            _job_set(job_id, f'Error: {str(e)}', 'error', error=str(e))


@app.route('/process-playlist', methods=['POST'])
def process_playlist():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    user_id  = session['user_id']
    name     = request.form.get('name', '').strip()
    source   = request.form.get('source', '').strip()
    if not name or not source:
        return jsonify({'error': 'Name and source are required'}), 400

    # Capture everything from request context before handing off to thread
    form_data  = request.form.to_dict()
    host_url   = request.host_url
    files_data = {}
    for key in request.files:
        f = request.files[key]
        files_data[key] = {'filename': secure_filename(f.filename), 'content': f.read()}

    # Purge stale jobs (> 30 min)
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    with _jobs_lock:
        for k in [k for k, v in _jobs.items() if v['created'] < cutoff]:
            del _jobs[k]

    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        _jobs[job_id] = {
            'status':   'running',
            'step':     'Queued…',
            'steps':    [],
            'created':  datetime.utcnow(),
            'analyzed': None,
            'error':    None,
        }

    t = threading.Thread(
        target=_bg_process_playlist,
        args=(app.app_context(), job_id, user_id, name, source, form_data, files_data, host_url),
        daemon=True,
    )
    t.start()
    return jsonify({'job_id': job_id})


@app.route('/job-status/<job_id>')
def job_status(job_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({
        'status':   job['status'],
        'step':     job['step'],
        'steps':    job['steps'][-10:],
        'analyzed': job.get('analyzed'),
        'error':    job.get('error'),
    })

# Create a new internal function for analysis
def analyze_playlist_internal(user_id, playlist_name):
    """Internal function to analyze playlist without HTTP request handling"""
    playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
    if not playlist:
        raise ValueError('Playlist not found')

    playlist_dir = BASE_DIR / 'static' / 'playlists' / str(user_id) / secure_filename(playlist_name)
    m3u_path = playlist_dir / 'tv.m3u'
    epg_path = playlist_dir / 'epg.xml'
    analysis_dir = playlist_dir / 'analysis'
    analysis_dir.mkdir(exist_ok=True)

    analyzer_script = BASE_DIR / 'm3u_analyzer_beefy-new.py'

    if not analyzer_script.exists():
        raise FileNotFoundError('Analyzer script not found')

    if not (m3u_path.exists() and epg_path.exists()):
        raise FileNotFoundError('Required files not found for analysis')

    # Run analyzer script
    result = subprocess.run(
        [sys.executable, str(analyzer_script), str(m3u_path), str(epg_path)],
        cwd=str(analysis_dir),
        capture_output=True,
        text=True,
        check=True
    )

    # Process command data and update playlist just like in analyze_playlist route
    command_file = analysis_dir / 'command.json'
    if command_file.exists():
        with open(command_file, 'r') as f:
            command_data = json.load(f)

        # Update playlist with statistics and command
        playlist.total_channels = command_data.get('total_channels', 0)
        playlist.total_epg_matches = command_data.get('total_epg_matches', 0)
        playlist.total_movies = command_data.get('total_movies', 0)
        playlist.total_series = command_data.get('total_series', 0)
        playlist.total_unmatched = command_data.get('total_unmatched', 0)

        # Build the m3u editor command with local paths
        channel_ids = command_data.get('channel_ids', '')
        if channel_ids:
            channel_list = channel_ids.split(',')
            formatted_channel_ids = "'" + "','".join(channel_list) + "'"
            
            playlist.m3u_editor_command = (
                f'python ./m3u-epg-editor-py3.py '
                f'-m="file://{str(m3u_path)}" '
                f'-e="file://{str(epg_path)}" '
                f'-g="{formatted_channel_ids}" '
                f'-d="{str(playlist_dir / "optimized")}" '
                '-gm=keep -r=12 -f=cleaned'
            )
        
        db.session.commit()

def process_api_line(form_data, m3u_path, epg_path, details):
    try:
        server = form_data['server']
        username = form_data['username']
        password = form_data['password']

        m3u_url = f"{server}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
        epg_url = f"{server}/xmltv.php?username={username}&password={password}"

        # Download files
        download_file(m3u_url, m3u_path)
        download_file(epg_url, epg_path)

        # Update details
        details.update({
            'server': server,
            'stream_base': normalize_origin(server),
            'username': username,
            'm3u_path': str(m3u_path),
            'epg_path': str(epg_path)
        })
        store_password(details, password)
        return True

    except Exception as e:
        app.logger.error(f"API Line processing error: {str(e)}")
        return False

def process_xtream_api(form_data, m3u_path, epg_path, details, host_url=None, progress_cb=None):
    def _prog(msg):
        if progress_cb:
            progress_cb(msg)

    try:
        server = (form_data.get('server') or form_data['server']).strip().rstrip('/')
        username = form_data.get('username') or form_data['username']
        password = form_data.get('password') or form_data['password']
        include_vod = form_data.get('include_vod') == 'true'
        include_series = form_data.get('include_series') == 'true'
        include_proxy = form_data.get('include_proxy') == 'true'
        series_limit_value = form_data.get('series_limit')
        series_limit = int(series_limit_value) if series_limit_value else None

        m3u_url = f"{server}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
        epg_url = f"{server}/xmltv.php?username={username}&password={password}"

        class MockArgs:
            def __init__(self, m3uurl, include_vod, include_series, include_proxy, proxy_base, series_limit=None):
                self.m3uurl = m3uurl
                self.include_vod = include_vod
                self.include_series = include_series
                self.include_proxy = include_proxy
                self.proxy_base = proxy_base
                self.series_limit = series_limit

        base = (host_url or request.host_url).rstrip('/')
        proxy_base = base + '/stream_proxy?url='
        mock_args = MockArgs(m3u_url, include_vod, include_series, include_proxy, proxy_base if include_proxy else None, series_limit)

        headers = {
            # This provider class can reject browser identities while allowing
            # IPTV clients. Keep Xtream API requests deterministic and aligned
            # with the clients that successfully use the same subscription.
            'User-Agent': 'VLC/3.0.20 LibVLC/3.0.20',
            'Connection': 'close'
        }

        _prog(f'Connecting to {server}…')
        m3u_response = editor.get_m3u_from_api(m3u_url, headers, mock_args, progress_cb=_prog)

        if not m3u_response or m3u_response.status_code != 200:
            raise ValueError(f"Failed to fetch M3U via Xtream API (Status: {m3u_response.status_code if m3u_response else 'N/A'})")

        # Some providers authenticate get.php but return empty arrays from
        # player_api.php. In that case use their conventional M3U response
        # rather than persisting a header-only playlist as a success.
        if b'#EXTINF:' not in m3u_response.content:
            _prog('Xtream API returned no entries; trying direct M3U endpoint')
            direct_response = requests.get(m3u_url, headers=headers, timeout=60)
            if direct_response.status_code != 200:
                provider = 'Cloudflare/provider origin' if direct_response.status_code == 520 else 'Provider'
                raise ValueError(
                    f'{provider} returned HTTP {direct_response.status_code} from the direct M3U endpoint'
                )
            if b'#EXTINF:' not in direct_response.content:
                raise ValueError(
                    'Provider returned an empty playlist from both the Xtream API '
                    'and direct M3U endpoint'
                )
            m3u_response = direct_response
            _prog('Direct M3U playlist received')

        _prog('Saving playlist file…')
        with open(m3u_path, 'wb') as f:
            f.write(m3u_response.content)

        _prog('Downloading EPG guide…')
        epg_available = True
        epg_warning = None
        try:
            download_file(epg_url, epg_path)
        except Exception as epg_error:
            # A valid Xtream account does not necessarily provide xmltv.php.
            # Retain its usable live/VOD playlist and supply a valid empty
            # XMLTV document for downstream processing.
            epg_available = False
            epg_warning = str(epg_error)
            epg_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n<tv></tv>\n',
                encoding='utf-8',
            )
            app.logger.warning(
                'Xtream playlist imported without provider EPG: %s',
                epg_warning,
            )
            _prog('Provider has no XMLTV guide; continuing without EPG')

        details.update({
            'server': server,
            'stream_base': normalize_origin(server),
            'username': username,
            'include_vod': include_vod,
            'include_series': include_series,
            'include_proxy': include_proxy,
            'series_limit': series_limit,
            'epg_available': epg_available,
            'epg_warning': epg_warning,
            'm3u_path': str(m3u_path),
            'epg_path': str(epg_path)
        })
        store_password(details, password)
        return True

    except Exception as e:
        app.logger.error(f"Xtream API processing error: {str(e)}")
        return False

def process_m3u_url(form_data, m3u_path, epg_path, details):
    try:
        m3u_url = form_data['m3u_url']
        epg_url = form_data['epg_url']

        # Download files
        download_file(m3u_url, m3u_path)
        download_file(epg_url, epg_path)

        # Update details
        details.update({
            'm3u_url': m3u_url,
            'epg_url': epg_url,
            'm3u_path': str(m3u_path),
            'epg_path': str(epg_path)
        })
        return True

    except Exception as e:
        app.logger.error(f"M3U URL processing error: {str(e)}")
        return False

def process_m3u_file(files, m3u_path, epg_path, details):
    try:
        if 'm3u_file' not in files:
            raise ValueError('M3U file must be provided')

        def _write(key, path):
            entry = files[key]
            if isinstance(entry, dict):
                with open(path, 'wb') as f:
                    f.write(entry['content'])
            else:
                entry.save(path)

        _write('m3u_file', m3u_path)
        if 'epg_file' in files:
            _write('epg_file', epg_path)

        details.update({'m3u_path': str(m3u_path), 'epg_path': str(epg_path)})
        return True

    except Exception as e:
        app.logger.error(f"M3U File processing error: {str(e)}")
        return False

def download_file(url, path):
    """Use the robust editor download logic with enhanced headers and DNS"""
    headers = {
        'User-Agent': editor.get_random_user_agent(),
        'Connection': 'close'
    }
    response = editor.perform_get_with_backups(url, headers, [])
    if response is not None and response.status_code == 200:
        with open(path, 'wb') as f:
            f.write(response.content)
    else:
        status = response.status_code if response is not None else 'No Response'
        raise ValueError(f"Failed to download {url} (Status: {status})")

@app.route('/delete-playlist', methods=['POST'])
def delete_playlist():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    try:
        user_id = session['user_id']
        playlist_name = request.json.get('name')
        
        if not playlist_name:
            return jsonify({'error': 'Playlist name is required'}), 400

        success, message = playlist_manager.delete_playlist(user_id, playlist_name)
        
        if success:
            return jsonify({'message': message})
        return jsonify({'error': message}), 400

    except Exception as e:
        app.logger.error(f"Error deleting playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500
    

# Add these new routes to app.py after the analyze-playlist route

@app.route('/static/playlists/<int:user_id>/<path:playlist_name>/analysis/<path:filename>')
def serve_analysis_file(user_id, playlist_name, filename):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        # Construct the relative path from the static directory
        relative_path = f'playlists/{user_id}/{secure_filename(playlist_name)}/analysis/{filename}'
        
        # Use send_from_directory with the static folder
        return send_from_directory(app.static_folder, relative_path)
    except Exception as e:
        app.logger.error(f"Error serving analysis file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/static/playlists/<int:user_id>/<path:playlist_name>/analysis/')
def serve_analysis_index(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        # Redirect to the matched content analysis by default
        relative_path = f'playlists/{user_id}/{secure_filename(playlist_name)}/analysis/content_analysis_matched.html'
        return send_from_directory(app.static_folder, relative_path)
    except Exception as e:
        app.logger.error(f"Error serving analysis index: {str(e)}")
        return jsonify({'error': str(e)}), 500
    

@app.route('/static/playlists/<int:user_id>/<path:playlist_name>/analysis_noepg')
def serve_analysis_unmatched(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        analysis_path = BASE_DIR / str(user_id) / 'playlists' / secure_filename(playlist_name) / 'analysis' / 'content_analysis_unmatched.html'
        if not analysis_path.exists():
            return jsonify({'error': 'Analysis not found'}), 404
            
        return send_from_directory(analysis_path.parent, 'content_analysis_unmatched.html')
    except Exception as e:
        app.logger.error(f"Error serving analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/static/playlist/<int:user_id>/<path:playlist_name>/analysis_notvg')
def serve_analysis_notvgid(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        analysis_path = BASE_DIR / str(user_id) / 'playlists' / secure_filename(playlist_name) / 'analysis' / 'content_analysis_no_tvg.html'
        if not analysis_path.exists():
            return jsonify({'error': 'Analysis not found'}), 404
            
        return send_from_directory(analysis_path.parent, 'content_analysis_no_tvg.html')
    except Exception as e:
        app.logger.error(f"Error serving analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/watch_video')
def watch_video():
    video_url = request.args.get('url', '')
    # Optionally decode the URL if it's encoded
    decoded_url = urllib.parse.unquote(video_url)
    
    # Check if the URL is already pointing to our stream_proxy and extract the real URL
    # This prevents double-proxying which can cause timeouts and failures
    if 'stream_proxy?url=' in decoded_url:
        try:
            parsed = urllib.parse.urlparse(decoded_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'url' in qs:
                # The inner URL might also be encoded, so we decode it
                decoded_url = urllib.parse.unquote(qs['url'][0])
        except Exception as e:
            app.logger.warning(f"Failed to unwrap proxy URL: {e}")

    return render_template('watch_video.html', video_url=decoded_url)

@app.route('/stream_proxy')
def stream_proxy():
    """Proxy IPTV streams to bypass CORS restrictions"""
    stream_url = request.args.get('url', '')
    if not stream_url:
        return 'No URL provided', 400
    
    # Decode URL if it's encoded
    decoded_url = urllib.parse.unquote(stream_url)
    
    try:
        # Stream the content from the IPTV server
        # Spoof User-Agent to look like a browser/player
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Connection': 'keep-alive'
        }
        
        # Connection timeout 15s, no read timeout (live streams send chunks indefinitely)
        response = requests.get(decoded_url, stream=True, timeout=(15, None), headers=headers)
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        # Create response with proper headers
        flask_response = make_response(generate())
        
        # Copy important headers from the original response
        if 'content-type' in response.headers:
            flask_response.headers['Content-Type'] = response.headers['content-type']
        
        # Add CORS headers
        flask_response.headers['Access-Control-Allow-Origin'] = '*'
        flask_response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        flask_response.headers['Access-Control-Allow-Headers'] = 'Origin, Content-Type, Accept'
        
        # Add caching headers
        flask_response.headers['Cache-Control'] = 'no-cache'
        
        return flask_response
        
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Stream proxy error: {str(e)}")
        return f'Stream error: {str(e)}', 500
    except Exception as e:
        app.logger.error(f"Stream proxy unexpected error: {str(e)}")
        return f'Proxy error: {str(e)}', 500

# Enhanced content analysis route
@app.route('/demo/enhanced/<int:user_id>/<path:playlist_name>')
def enhanced_content_analysis(user_id, playlist_name):
    """Enhanced content analysis UI with collapsible groups, search, and performance optimizations"""
    try:
        # Verify user access
        if 'user_id' not in session or session['user_id'] != user_id:
            return redirect(url_for('auth.login'))
        
        # Get analysis directory path
        analysis_dir = os.path.join('static', 'playlists', str(user_id), secure_filename(playlist_name), 'analysis')
        
        # Check if analysis exists
        if not os.path.exists(analysis_dir):
            return "Analysis not found. Please run analysis first.", 404
            
        # Check for analysis files
        analysis_files = {
            'matched': os.path.join(analysis_dir, 'content_analysis_matched.html'),
            'movies': os.path.join(analysis_dir, 'content_analysis_movies.html'),
            'series': os.path.join(analysis_dir, 'content_analysis_series.html'),
            'unmatched': os.path.join(analysis_dir, 'content_analysis_unmatched.html'),
            'no_tvg': os.path.join(analysis_dir, 'content_analysis_unmatched_no_tvg.html')
        }
        
        # Find which analysis files exist
        available_files = {k: v for k, v in analysis_files.items() if os.path.exists(v)}

        if not available_files:
            return "No analysis files found. Please run analysis first.", 404

        # Read stats from command.json for tab counts
        import json as _json
        stats = {}
        command_json = os.path.join(analysis_dir, 'command.json')
        if os.path.exists(command_json):
            with open(command_json) as f:
                stats = _json.load(f)

        # Serve enhanced analysis version
        return render_template('enhanced_content_analysis.html',
                             user_id=user_id,
                             playlist_name=playlist_name,
                             safe_playlist_name=secure_filename(playlist_name),
                             analysis_files=available_files,
                             stats=stats)
                             
    except Exception as e:
        app.logger.error(f"Enhanced analysis error: {str(e)}")
        return f"Error loading enhanced analysis: {str(e)}", 500

# Update the analyze_playlist route
@app.route('/analyze-playlist', methods=['POST'])
def analyze_playlist():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    try:
        user_id = session['user_id']
        playlist_name = request.json.get('name')
        
        if not playlist_name:
            return jsonify({'error': 'Playlist name is required'}), 400

        # Get the playlist from the database
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        playlist_dir = BASE_DIR / 'static' / 'playlists' / str(user_id) / secure_filename(playlist_name)
        m3u_path = playlist_dir / 'tv.m3u'
        epg_path = playlist_dir / 'epg.xml'
        analysis_dir = playlist_dir / 'analysis'
        analysis_dir.mkdir(exist_ok=True)

        analyzer_script = BASE_DIR / 'm3u_analyzer_beefy-new.py'

        if not analyzer_script.exists():
            return jsonify({'error': 'Analyzer script not found'}), 500

        if not (m3u_path.exists() and epg_path.exists()):
            return jsonify({'error': 'Required files not found for analysis'}), 400

        # Run analyzer script
        result = subprocess.run(
            [sys.executable, str(analyzer_script), str(m3u_path), str(epg_path)],
            cwd=str(analysis_dir),
            capture_output=True,
            text=True,
            check=True
        )

        # Read the command data
        command_file = analysis_dir / 'command.json'
        if command_file.exists():
            with open(command_file, 'r') as f:
                command_data = json.load(f)

            # Update playlist with statistics and command
            playlist.total_channels = command_data.get('total_channels', 0)
            playlist.total_epg_matches = command_data.get('total_epg_matches', 0)
            playlist.total_movies = command_data.get('total_movies', 0)
            playlist.total_series = command_data.get('total_series', 0)
            playlist.total_unmatched = command_data.get('total_unmatched', 0)

            # Build the m3u editor command with local paths
            channel_ids = command_data.get('channel_ids', '')
            if channel_ids:
                channel_list = channel_ids.split(',')
                formatted_channel_ids = "'" + "','".join(channel_list) + "'"
                
                playlist.m3u_editor_command = (
                    f'python ./m3u-epg-editor-py3.py '
                    f'-m="file://{str(m3u_path)}" '
                    f'-e="file://{str(epg_path)}" '
                    f'-g="{formatted_channel_ids}" '
                    f'-d="{str(playlist_dir / "optimized")}" '
                    '-gm=keep -r=12 -f=cleaned'
                )
            
            db.session.commit()

        # Check for the analysis file
        analysis_file = analysis_dir / 'content_analysis_matched.html'
        if not analysis_file.exists():
            return jsonify({'error': 'Analysis file was not generated'}), 500

        return jsonify({
            'message': 'Analysis completed successfully',
            'analysis_url': url_for('static', filename=f'playlists/{user_id}/{secure_filename(playlist_name)}/analysis/content_analysis_matched.html'),
            'command': playlist.m3u_editor_command
        })

    except subprocess.CalledProcessError as e:
        app.logger.error(f"Analysis script error: {e.stderr}")
        return jsonify({'error': 'Analysis script failed'}), 500
    except Exception as e:
        app.logger.error(f"Error analyzing playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/optimize-playlist', methods=['POST'])
def optimize_playlist():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    try:
        user_id = session['user_id']
        playlist_name = request.json.get('name')
        
        if not playlist_name:
            return jsonify({'error': 'Playlist name is required'}), 400

        # Get the playlist
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        if not playlist.m3u_editor_command:
            app.logger.error("No m3u_editor_command found in playlist")
            return jsonify({'error': 'Please run analysis first'}), 400

        # Get the playlist directory and files
        playlist_dir = BASE_DIR / 'static' / 'playlists' / str(user_id) / secure_filename(playlist_name)
        m3u_path = playlist_dir / 'tv.m3u'
        epg_path = playlist_dir / 'epg.xml'
        editor_script = BASE_DIR / 'm3u-epg-editor-py3.py'
        optimized_dir = playlist_dir / 'optimized'
        optimized_dir.mkdir(exist_ok=True, parents=True)

        # Just extract the groups from the command - we'll use local paths for files
        groups_match = re.search(r'-g="([^"]+)"', playlist.m3u_editor_command)
        if not groups_match:
            app.logger.error("Failed to extract groups from command")
            return jsonify({'error': 'Invalid command format'}), 400

        groups = groups_match.group(1)

        # Run optimization with the interpreter hosting this application. This
        # works for both Windows virtual environments and Unix deployments.
        python_executable = sys.executable

        # Build command parts with local file paths
        # Build command parts with local file paths
        command_parts = [
            python_executable,
            str(editor_script),
            f'-m=file://{str(m3u_path)}',  # Add file:// protocol
            f'-e=file://{str(epg_path)}',   # Add file:// protocol
            f'-g={groups}',
            f'-d={str(optimized_dir)}',
            '-gm=keep',
            '-r=12',
            '-f=cleaned'
        ]

        app.logger.info("Command parts:")
        for part in command_parts:
            app.logger.info(f"  {part}")

        env = os.environ.copy()
        env['PYTHONPATH'] = str(BASE_DIR)

        try:
            result = subprocess.run(
                command_parts,
                capture_output=True,
                text=True,
                check=True,
                env=env,
                cwd=str(BASE_DIR)
            )
            app.logger.info(f"Command stdout: {result.stdout}")
            if result.stderr:
                app.logger.warning(f"Command stderr: {result.stderr}")

        except subprocess.CalledProcessError as e:
            app.logger.error(f"Command failed with return code: {e.returncode}")
            app.logger.error(f"Command stdout: {e.stdout}")
            app.logger.error(f"Command stderr: {e.stderr}")
            raise

        # Verify output files were created
        if not (optimized_dir / 'cleaned.m3u8').exists() or not (optimized_dir / 'cleaned.xml').exists():
            app.logger.error("Output files were not created")
            return jsonify({'error': 'Output files were not created'}), 500

        return jsonify({
            'message': 'Playlist optimization completed successfully',
            'output_dir': str(optimized_dir)
        })

    except subprocess.CalledProcessError as e:
        app.logger.error(f"Optimization script error: {e.stderr}")
        return jsonify({'error': f'Optimization script failed: {e.stdout}\n{e.stderr}'}), 500
    except Exception as e:
        app.logger.error(f"Error optimizing playlist: {str(e)}")
        app.logger.error(f"Exception type: {type(e)}")
        import traceback
        app.logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/static/playlists/<int:user_id>/<path:playlist_name>/<path:filename>')
def serve_playlist_file(user_id, playlist_name, filename):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        # Construct the relative path from the static directory
        relative_path = f'playlists/{user_id}/{secure_filename(playlist_name)}/{filename}'
        
        # Log the requested path
        app.logger.info(f"Serving file: {relative_path}")
        app.logger.info(f"Static folder: {app.static_folder}")
        
        # Use send_from_directory with the static folder
        return send_from_directory(app.static_folder, relative_path)
    except Exception as e:
        app.logger.error(f"Error serving file: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/stream/<string:token>/<path:playlist_name>/<string:filetype>')
def stream_playlist_file(token, playlist_name, filetype):
    """Public no-auth route for media players. Token identifies the user."""
    if filetype not in ['tv.m3u', 'epg.xml', 'tv_edited.m3u']:
        return jsonify({'error': 'Invalid file type'}), 400

    from models import User
    user = User.query.filter_by(stream_token=token).first()
    if not user:
        return jsonify({'error': 'Not found'}), 404

    try:
        relative_path = f'playlists/{user.id}/{secure_filename(playlist_name)}/{filetype}'
        file_path = os.path.join(app.static_folder, relative_path)
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        response = send_from_directory(app.static_folder, relative_path)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        app.logger.error(f"Error serving stream file: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/playlist/<int:user_id>/<path:playlist_name>/export/jellyfin', methods=['POST'])
def export_playlist_for_jellyfin(user_id, playlist_name):
    """Generate Jellyfin artifacts from the playlist's saved edited state."""
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
    if not playlist:
        return jsonify({'error': 'Playlist not found'}), 404

    try:
        from models import User
        user = User.query.get(user_id)
        safe_name = secure_filename(playlist_name)
        public_base = (
            request.host_url.rstrip('/')
            + f'/stream/{user.stream_token}/{safe_name}/jellyfin'
        )
        playlist_path = playlist_manager.get_playlist_path(user_id, playlist_name)
        manifest = generate_jellyfin_export(
            playlist_path,
            public_base_url=public_base,
        )
        vod_counts = generate_vod_fixture(
            (playlist_path / 'tv_edited.m3u') if (playlist_path / 'tv_edited.m3u').exists()
            else (playlist_path / 'tv.m3u'),
            playlist_path / 'exports' / 'jellyfin' / 'vod-fixture',
        )
        manifest['vod'] = {
            'counts': vod_counts,
            'package_url': f'{public_base}/vod-fixture.zip',
        }
        return jsonify(manifest)
    except (FileNotFoundError, ValueError) as error:
        return jsonify({'error': str(error)}), 400
    except Exception as error:
        app.logger.exception('Jellyfin export failed')
        return jsonify({'error': str(error)}), 500


@app.route('/stream/<string:token>/<path:playlist_name>/jellyfin/<string:filename>')
def stream_jellyfin_export(token, playlist_name, filename):
    """Serve generated Jellyfin artifacts through the existing user token."""
    allowed = {'live.m3u8', 'epg.xml', 'manifest.json', 'validation.json', 'vod-fixture.zip'}
    if filename not in allowed:
        return jsonify({'error': 'Invalid artifact'}), 400

    from models import User
    user = User.query.filter_by(stream_token=token).first()
    if not user:
        return jsonify({'error': 'Not found'}), 404

    export_root = (
        playlist_manager.get_playlist_path(user.id, playlist_name)
        / 'exports' / 'jellyfin'
    )
    export_dir = export_root if filename == 'vod-fixture.zip' else export_root / 'default'
    if not (export_dir / filename).exists():
        return jsonify({'error': 'Artifact not found'}), 404
    response = send_from_directory(export_dir, filename)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


@app.route('/static/playlists/<int:user_id>/<path:playlist_name>/<string:filetype>')
def serve_m3u_epg_file(user_id, playlist_name, filetype):
    if filetype not in ['tv.m3u', 'epg.xml', 'tv_edited.m3u']:
        return jsonify({'error': 'Invalid file type'}), 400

    try:
        # Construct the relative path from the static directory
        relative_path = f'playlists/{user_id}/{secure_filename(playlist_name)}/{filetype}'
        
        # Log the requested path
        app.logger.info(f"Serving {filetype} file: {relative_path}")
        
        # Get the full file path
        file_path = os.path.join(app.static_folder, relative_path)
        
        # Verify file exists
        if not os.path.exists(file_path):
            app.logger.error(f"File not found: {file_path}")
            return jsonify({'error': 'File not found'}), 404

        # Return the file without authentication check
        response = send_from_directory(app.static_folder, relative_path)
        
        # Add CORS headers to allow access from any origin
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
        
    except Exception as e:
        app.logger.error(f"Error serving {filetype} file: {str(e)}")
        return jsonify({'error': str(e)}), 500
    

@app.route('/playlist/<int:user_id>/<path:playlist_name>/edit')
def edit_playlist(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        # Get the playlist from the database
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        playlist_dir = playlist_manager.get_playlist_path(user_id, playlist_name)
        m3u_path = playlist_dir / 'tv.m3u'
        edited_m3u_path = playlist_dir / 'tv_edited.m3u'

        if not m3u_path.exists():
            return jsonify({'error': 'M3U file not found'}), 404

        # Create edited copy from source on first open (source is never modified)
        if not edited_m3u_path.exists():
            shutil.copy2(m3u_path, edited_m3u_path)

        # Parse the edited working copy (not the protected source)
        groups = defaultdict(list)
        current_channel = None
        total_channels = 0

        with open(edited_m3u_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    # Extract channel info
                    group_match = re.search(r'group-title="([^"]+)"', line)
                    name_match = re.search(r'",(.+)$', line)
                    tvg_id_match = re.search(r'tvg-id="([^"]+)"', line)
                    logo_match = re.search(r'tvg-logo="([^"]+)"', line)

                    if group_match and name_match:
                        current_channel = {
                            'name': name_match.group(1).strip(),
                            'group': group_match.group(1),
                            'tvg_id': tvg_id_match.group(1) if tvg_id_match else '',
                            'logo': logo_match.group(1) if logo_match else '',
                            'extinf': line,  # Store original EXTINF line
                            'visible': True  # Default visibility state
                        }
                elif line and not line.startswith('#') and current_channel:
                    current_channel['url'] = line
                    groups[current_channel['group']].append(current_channel)
                    total_channels += 1
                    current_channel = None

        # Convert to list of group metadata only — channels loaded on demand
        group_list = [
            {
                'name': group_name,
                'channel_count': len(channels),
                'visible': True
            }
            for group_name, channels in sorted(groups.items())
        ]

        # Statistics for the editor header
        stats = {
            'total_groups': len(group_list),
            'total_channels': total_channels,
            'total_visible_channels': total_channels  # Initially all channels are visible
        }

        return render_template('playlist_editor.html', 
                             playlist=playlist,
                             groups=group_list,
                             stats=stats)

    except Exception as e:
        app.logger.error(f"Error loading playlist editor: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/playlist/<int:user_id>/<path:playlist_name>/group/<int:group_idx>/channels')
def get_group_channels(user_id, playlist_name, group_idx):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        playlist_dir = playlist_manager.get_playlist_path(user_id, playlist_name)
        edited_m3u_path = playlist_dir / 'tv_edited.m3u'
        if not edited_m3u_path.exists():
            return jsonify({'error': 'Edited M3U not found — open the editor first'}), 404

        groups = defaultdict(list)
        current_channel = None
        with open(edited_m3u_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    group_match = re.search(r'group-title="([^"]+)"', line)
                    name_match = re.search(r'",(.+)$', line)
                    logo_match = re.search(r'tvg-logo="([^"]+)"', line)
                    if group_match and name_match:
                        current_channel = {
                            'name': name_match.group(1).strip(),
                            'group': group_match.group(1),
                            'logo': logo_match.group(1) if logo_match else '',
                            'extinf': line,
                            'visible': True
                        }
                elif line and not line.startswith('#') and current_channel:
                    current_channel['url'] = line
                    groups[current_channel['group']].append(current_channel)
                    current_channel = None

        sorted_names = sorted(groups.keys())
        if group_idx >= len(sorted_names):
            return jsonify({'error': 'Group index out of range'}), 404

        return jsonify({'channels': groups[sorted_names[group_idx]]})

    except Exception as e:
        app.logger.error(f"Error loading group channels: {str(e)}")
        return jsonify({'error': str(e)}), 500


# Add route to save edited playlist
@app.route('/playlist/<int:user_id>/<path:playlist_name>/save', methods=['POST'])
def save_edited_playlist(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        # Get the base playlist directory
        playlist_dir = Path(app.static_folder) / 'playlists' / str(user_id) / secure_filename(playlist_name)
        
        # Ensure the directory exists
        playlist_dir.mkdir(parents=True, exist_ok=True)
        
        # tv.m3u = protected source (never modified); tv_edited.m3u = working copy
        edited_m3u_path = playlist_dir / 'tv_edited.m3u'
        temp_m3u_path = playlist_dir / 'tv_edited.tmp'

        data = request.json
        if not data or 'groups' not in data:
            return jsonify({'error': 'Invalid data format'}), 400

        # Pre-parse current edited file to fill in groups the user never opened
        existing_by_group = defaultdict(list)
        if edited_m3u_path.exists():
            cur = None
            with open(edited_m3u_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#EXTINF:'):
                        gm = re.search(r'group-title="([^"]+)"', line)
                        if gm:
                            cur = {'extinf': line, 'group': gm.group(1)}
                    elif line and not line.startswith('#') and cur:
                        existing_by_group[cur['group']].append({'extinf': cur['extinf'], 'url': line})
                        cur = None
        sorted_existing_names = sorted(existing_by_group.keys())

        # Write new edited M3U (source tv.m3u is never touched)
        try:
            with open(temp_m3u_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
                for i, group in enumerate(data['groups']):
                    if not group.get('visible', True):
                        continue
                    channels = group.get('channels')
                    if channels is None:
                        # Group never opened — copy its current state from edited file
                        group_name = sorted_existing_names[i] if i < len(sorted_existing_names) else None
                        if group_name:
                            for ch in existing_by_group[group_name]:
                                f.write(f"{ch['extinf']}\n{ch['url']}\n")
                    else:
                        for channel in channels:
                            if channel.get('visible', True):
                                extinf = channel.get('extinf', '')
                                url = channel.get('url', '')
                                if extinf and url:
                                    f.write(f"{extinf}\n{url}\n")

            shutil.move(temp_m3u_path, edited_m3u_path)

            # Update database
            playlist = Playlist.query.filter_by(
                user_id=user_id,
                name=playlist_name
            ).first()

            if playlist:
                playlist.last_sync = datetime.utcnow()
                db.session.commit()

            return jsonify({'message': 'Playlist saved successfully'})

        except IOError as e:
            app.logger.error(f"IO Error while saving playlist: {str(e)}")
            if temp_m3u_path.exists():
                temp_m3u_path.unlink()  # Clean up temp file if it exists
            return jsonify({'error': f'Failed to save playlist: {str(e)}'}), 500

    except Exception as e:
        app.logger.error(f"Error saving edited playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500


def detect_stream_base(m3u_path):
    """Auto-detect the stream host base URL from the first stream entry in an M3U file."""
    try:
        with open(m3u_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if 'stream_proxy?url=' in line:
                        encoded = line.split('stream_proxy?url=', 1)[1]
                        line = urllib.parse.unquote(encoded)
                    parsed = urllib.parse.urlparse(line)
                    if parsed.scheme and parsed.netloc:
                        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return None


def apply_mirror_substitution(content, stream_base, active_mirror):
    """Substitute the stream base URL with the active mirror in M3U content."""
    return rewrite_provider_url(content, stream_base, active_mirror)
    # Proxy-wrapped URLs encode only the colon: http%3A//hostname — use safe='/'


@app.route('/playlist/<int:user_id>/<path:playlist_name>/mirrors', methods=['GET'])
def get_mirrors(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        details = dict(playlist.details or {})

        if not details.get('stream_base'):
            m3u_path = playlist_manager.get_playlist_path(user_id, playlist_name) / 'tv.m3u'
            base = detect_stream_base(m3u_path)
            if base:
                details['stream_base'] = base
                playlist.details = details
                db.session.commit()

        return jsonify({
            'mirrors':        details.get('mirrors', []),
            'active_mirror':  details.get('active_mirror'),
            'stream_base':    details.get('stream_base'),
            'source':         playlist.source,
            'include_vod':    bool(details.get('include_vod', False)),
            'include_series': bool(details.get('include_series', False)),
            'include_proxy':  bool(details.get('include_proxy', False)),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/playlist/<int:user_id>/<path:playlist_name>/mirrors', methods=['POST'])
def save_mirrors(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        data = request.json or {}
        details = dict(playlist.details or {})
        mirrors = normalize_mirrors(data.get('mirrors', []))
        active = normalize_origin(data.get('active_mirror'))
        if active and active.casefold() not in {item.casefold() for item in mirrors}:
            raise ValueError('Active mirror must be included in the ordered mirror list')
        details['mirrors'] = mirrors
        details['active_mirror'] = active
        if 'include_vod' in data:
            details['include_vod']    = bool(data['include_vod'])
        if 'include_series' in data:
            details['include_series'] = bool(data['include_series'])
        if 'include_proxy' in data:
            details['include_proxy']  = bool(data['include_proxy'])
        playlist.details = details
        db.session.commit()
        return jsonify({'message': 'Mirrors saved.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/playlist/<int:user_id>/<path:playlist_name>/serve/source')
def serve_source_playlist(user_id, playlist_name):
    """Serve tv.m3u (protected source) with active mirror substitution applied."""
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    playlist_dir = playlist_manager.get_playlist_path(user_id, playlist_name)
    source_path = playlist_dir / 'tv.m3u'
    if not source_path.exists():
        return jsonify({'error': 'Source playlist not found'}), 404

    playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
    details = (playlist.details or {}) if playlist else {}

    with open(source_path, 'r', encoding='utf-8') as f:
        content = f.read()

    content = apply_mirror_substitution(content, details.get('stream_base'), details.get('active_mirror'))
    response = make_response(content)
    response.headers['Content-Type'] = 'application/x-mpegurl'
    response.headers['Content-Disposition'] = f'attachment; filename="{secure_filename(playlist_name)}_source.m3u"'
    return response


@app.route('/playlist/<int:user_id>/<path:playlist_name>/serve/edited')
def serve_edited_playlist(user_id, playlist_name):
    """Serve tv_edited.m3u with active mirror substitution applied."""
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    playlist_dir = playlist_manager.get_playlist_path(user_id, playlist_name)
    edited_path = playlist_dir / 'tv_edited.m3u'

    if not edited_path.exists():
        return jsonify({'error': 'No edited playlist yet — open the editor first'}), 404

    playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
    details = (playlist.details or {}) if playlist else {}

    with open(edited_path, 'r', encoding='utf-8') as f:
        content = f.read()

    content = apply_mirror_substitution(content, details.get('stream_base'), details.get('active_mirror'))
    response = make_response(content)
    response.headers['Content-Type'] = 'application/x-mpegurl'
    response.headers['Content-Disposition'] = f'attachment; filename="{secure_filename(playlist_name)}_edited.m3u"'
    return response


@app.route('/playlist/<int:user_id>/<path:playlist_name>/refresh-source', methods=['POST'])
def refresh_source(user_id, playlist_name):
    """Re-download source files using stored credentials. Never touches tv_edited.m3u."""
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        details = playlist.details or {}
        source = playlist.source
        playlist_dir = playlist_manager.get_playlist_path(user_id, playlist_name)
        m3u_path = playlist_dir / 'tv.m3u'
        epg_path = playlist_dir / 'epg.xml'

        if source in ('API Line', 'Xtream API'):
            username = details.get('username')
            password = decrypt_password(details)
            server = details.get('active_mirror') or details.get('server')
            if not all([server, username, password]):
                return jsonify({'error': 'Stored credentials incomplete'}), 400
            m3u_url = f"{server}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
            epg_url = f"{server}/xmltv.php?username={username}&password={password}"

            if source == 'Xtream API':
                refresh_form = {
                    'server': server,
                    'username': username,
                    'password': password,
                    'include_vod': str(bool(details.get('include_vod'))).lower(),
                    'include_series': str(bool(details.get('include_series'))).lower(),
                    'include_proxy': str(bool(details.get('include_proxy'))).lower(),
                }
                if not process_xtream_api(
                    refresh_form, m3u_path, epg_path, details,
                    host_url=request.host_url,
                ):
                    return jsonify({'error': 'Failed to refresh Xtream playlist'}), 502
            else:
                download_file(m3u_url, m3u_path)
                download_file(epg_url, epg_path)

        elif source == 'M3U Url':
            m3u_url = details.get('m3u_url')
            epg_url = details.get('epg_url')
            if not m3u_url:
                return jsonify({'error': 'No M3U URL stored'}), 400
            download_file(m3u_url, m3u_path)
            if epg_url:
                download_file(epg_url, epg_path)

        elif source == 'M3U File':
            return jsonify({'error': 'File uploads cannot be refreshed — re-upload manually'}), 400

        else:
            return jsonify({'error': f'Unknown source type: {source}'}), 400

        playlist.last_sync = datetime.utcnow()
        db.session.commit()

        return jsonify({'message': f'Source refreshed from {source}. Your edited playlist is unchanged.'})

    except Exception as e:
        app.logger.error(f"Error refreshing source: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/playlist/<int:user_id>/<path:playlist_name>/download', methods=['POST'])
def download_playlist(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        # Construct the path to the edited m3u file
        playlist_dir = Path(app.static_folder) / 'playlists' / str(user_id) / f"{secure_filename(playlist_name)}_edit"
        m3u_path = playlist_dir / 'tv.m3u'
        
        if not m3u_path.exists():
            return jsonify({'error': 'Playlist file not found'}), 404

        # Read and return the actual file
        with open(m3u_path, 'r', encoding='utf-8') as f:
            m3u_content = f.read()

        response = make_response(m3u_content)
        response.headers['Content-Type'] = 'application/x-mpegurl'
        response.headers['Content-Disposition'] = f'attachment; filename=playlists/{user_id}/{secure_filename(playlist_name)}_edit/tv.m3u'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Error downloading playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jellyfin/plugin-repository/manifest.json')
def jellyfin_plugin_repository_manifest():
    """Publish the Jellyfin catalog with package URLs for this deployment."""
    configured_url = os.getenv('M3UGUIDE_PUBLIC_URL', '').strip()
    public_url = configured_url or request.url_root
    if not public_url.lower().startswith(('http://', 'https://')):
        return jsonify({'error': 'M3UGUIDE_PUBLIC_URL must be an HTTP(S) URL'}), 500

    try:
        manifest = build_manifest(
            PLUGIN_REPOSITORY_DIR / 'manifest.json',
            public_url,
            '/api/jellyfin/plugin-repository/packages',
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        app.logger.error('Plugin repository manifest is invalid: %s', error)
        return jsonify({'error': 'Plugin repository is unavailable'}), 503

    response = jsonify(manifest)
    response.headers['Cache-Control'] = 'no-cache, max-age=0'
    return response


@app.route('/api/jellyfin/plugin-repository/packages/<string:filename>')
def jellyfin_plugin_repository_package(filename):
    """Serve one immutable, explicitly versioned plugin package."""
    if filename != 'm3u-logo.jpg' and not PACKAGE_NAME.fullmatch(filename):
        return jsonify({'error': 'Plugin package not found'}), 404
    response = send_from_directory(PLUGIN_REPOSITORY_DIR, filename, as_attachment=True)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Server Error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', '4444'))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    # Log startup information
    app.logger.info(f"Starting application on port {port}")
    app.logger.info(f"Debug mode: {debug}")
    app.logger.info(f"Environment: {os.getenv('FLASK_ENV', 'production')}")
    
    try:
        app.run(
            host='0.0.0.0',
            port=port,
            debug=debug
        )
    except Exception as e:
        app.logger.error(f"Failed to start application: {str(e)}")
