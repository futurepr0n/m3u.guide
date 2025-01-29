from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, render_template
import os
import requests
import subprocess
import tempfile
import secrets
import logging
from datetime import datetime, timedelta
from flask_session import Session
import shutil
from pathlib import Path
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from werkzeug.utils import secure_filename
from models import db, init_db, User, Playlist
from auth import auth
import urllib.parse
import re
import json
from collections import defaultdict


# Load environment variables
load_dotenv()

# Configure base directories
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
TEMPLATES_DIR = BASE_DIR / 'templates'
LOG_DIR = BASE_DIR / 'logs'

# Ensure directories exist
for directory in [STATIC_DIR, TEMPLATES_DIR, LOG_DIR]:
    directory.mkdir(exist_ok=True)

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
    SESSION_FILE_DIR=tempfile.gettempdir(),
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

# Register blueprints
app.register_blueprint(auth, url_prefix='/auth')


# Initialize PlaylistManager
playlist_manager = PlaylistManager(BASE_DIR)

# Configure logging
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

@app.route('/')
def serve_index():
    if 'user_id' in session:
        return render_template('index.html')
    return redirect(url_for('auth.login'))

@app.route('/get-playlists')
def get_playlists():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403
    
    playlists = playlist_manager.get_user_playlists(session['user_id'])
    return jsonify({
        'user_id': session['user_id'],
        'playlists': [{
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
            'has_analysis': os.path.exists(os.path.join(
                app.static_folder,
                'playlists',
                str(session['user_id']),
                secure_filename(p.name),
                'analysis',
                'content_analysis_matched.html'
            ))
        } for p in playlists]
    })

@app.route('/process-playlist', methods=['POST'])
def process_playlist():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 403

    try:
        user_id = session['user_id']
        name = request.form['name']
        source = request.form['source']

        # Create playlist directory in static folder
        playlist_dir = playlist_manager.get_playlist_path(user_id, name)
        playlist_dir.mkdir(parents=True, exist_ok=True)
        app.logger.info(f"Created directory: {playlist_dir}")

        # Paths for playlist files
        m3u_path = playlist_dir / 'tv.m3u'
        epg_path = playlist_dir / 'epg.xml'

        playlist_data = {
            'name': name,
            'source': source,
            'details': {}
        }

        # Handle different source types
        if source == 'API Line':
            success = process_api_line(
                request.form,
                m3u_path,
                epg_path,
                playlist_data['details']
            )
        elif source == 'M3U Url':
            success = process_m3u_url(
                request.form,
                m3u_path,
                epg_path,
                playlist_data['details']
            )
        elif source == 'M3U File':
            success = process_m3u_file(
                request.files,
                m3u_path,
                epg_path,
                playlist_data['details']
            )
        else:
            return jsonify({'error': 'Invalid source type'}), 400

        if not success:
            return jsonify({'error': 'Failed to process playlist'}), 500

        # Add playlist to database
        playlist_manager.add_playlist(user_id, playlist_data)
        return jsonify({'message': 'Playlist processed successfully'})

    except Exception as e:
        app.logger.error(f"Error processing playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
            'username': username,
            'password': password,
            'm3u_path': str(m3u_path),
            'epg_path': str(epg_path)
        })
        return True

    except Exception as e:
        app.logger.error(f"API Line processing error: {str(e)}")
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
        if 'm3u_file' not in files or 'epg_file' not in files:
            raise ValueError('Both M3U and EPG files must be provided')
        
        # Save files
        files['m3u_file'].save(m3u_path)
        files['epg_file'].save(epg_path)

        # Update details
        details.update({
            'm3u_path': str(m3u_path),
            'epg_path': str(epg_path)
        })
        return True

    except Exception as e:
        app.logger.error(f"M3U File processing error: {str(e)}")
        return False

def download_file(url, path):
    response = requests.get(url)
    response.raise_for_status()
    with open(path, 'wb') as f:
        f.write(response.content)

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
    return render_template('watch_video.html', video_url=decoded_url)

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

        analyzer_script = BASE_DIR / 'm3u_analyzer_beefy.py'

        if not analyzer_script.exists():
            return jsonify({'error': 'Analyzer script not found'}), 500

        if not (m3u_path.exists() and epg_path.exists()):
            return jsonify({'error': 'Required files not found for analysis'}), 400

        # Run analyzer script
        result = subprocess.run(
            ['python3', str(analyzer_script), str(m3u_path), str(epg_path)],
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


            # Build the m3u editor command
            channel_ids = command_data.get('channel_ids', '')
            if channel_ids:
                channel_list = channel_ids.split(',')
                formatted_channel_ids = "'" + "','".join(channel_list) + "'"
                # Build URLs
                base_url = "http://m3u-toolkit.futurepr0n.com"
                m3u_url = f"{base_url}/static/playlists/{user_id}/{secure_filename(playlist_name)}/tv.m3u"
                epg_url = f"{base_url}/static/playlists/{user_id}/{secure_filename(playlist_name)}/epg.xml"
                
                playlist.m3u_editor_command = (
                    f'python ./m3u-epg-editor-py3.py '
                    f'-m="{m3u_url}" '  # Use URL instead of file path
                    f'-e="{epg_url}" '  # Use URL instead of file path
                    f'-g="{formatted_channel_ids}" '
                    f'-d="{str(playlist_dir / "optimized")}" '
                    '-gm=keep -r=12 -f=cleaned'
                )
            
            
            db.session.commit()
        
        
        
        # Extract statistics from the generated analysis file
        analysis_file = analysis_dir / 'content_analysis_matched.html'
        if not analysis_file.exists():
            return jsonify({'error': 'Analysis file was not generated'}), 500

        # Parse the analysis file to extract statistics
        with open(analysis_file, 'r') as f:
            content = f.read()
            
        # Extract statistics using regex
        import re
        total_channels = int(re.search(r'Total Channels with TVG-ID: (\d+)', content).group(1))
        total_epg_matches = int(re.search(r'Channels with EPG Matches: (\d+)', content).group(1))
        total_movies = int(re.search(r'Movies without TVG-ID: (\d+)', content).group(1))
        total_series = int(re.search(r'Series without TVG-ID: (\d+)', content).group(1))
        total_unmatched = int(re.search(r'Unmatched Content without TVG-ID: (\d+)', content).group(1))
        
        # Update playlist with statistics
        playlist.total_channels = total_channels
        playlist.total_epg_matches = total_epg_matches
        playlist.total_movies = total_movies
        playlist.total_series = total_series
        playlist.total_unmatched = total_unmatched
        
        db.session.commit()
            
        return jsonify({
            'message': 'Analysis completed successfully',
            'analysis_url': url_for('static', filename=f'playlists/{user_id}/{secure_filename(playlist_name)}/analysis/content_analysis_matched.html'),
            'command': command_data.get('m3u_editor_command', '') if command_file.exists() else None
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

        # Get the playlist directory
        playlist_dir = BASE_DIR / 'static' / 'playlists' / str(user_id) / secure_filename(playlist_name)
        editor_script = BASE_DIR / 'm3u-epg-editor-py3.py'
        optimized_dir = playlist_dir / 'optimized'
        optimized_dir.mkdir(exist_ok=True)

        # Extract values from command using regex
        m3u_match = re.search(r'-m="([^"]+)"', playlist.m3u_editor_command)
        epg_match = re.search(r'-e="([^"]+)"', playlist.m3u_editor_command)
        groups_match = re.search(r'-g="([^"]+)"', playlist.m3u_editor_command)

        if not all([m3u_match, epg_match, groups_match]):
            app.logger.error("Failed to extract required values from command")
            return jsonify({'error': 'Invalid command format'}), 400

        m3u_url = m3u_match.group(1)
        epg_url = epg_match.group(1)
        groups = groups_match.group(1)

        # Use python from virtual environment if available
        venv_python = BASE_DIR / 'venv' / 'bin' / 'python3'
        python_executable = str(venv_python) if venv_python.exists() else 'python3'

        # Build command parts without extra quotes
        command_parts = [
            python_executable,
            str(editor_script),
            f'-m={m3u_url}',
            f'-e={epg_url}',
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
    
@app.route('/static/playlists/<int:user_id>/<path:playlist_name>/<string:filetype>')
def serve_m3u_epg_file(user_id, playlist_name, filetype):
    if filetype not in ['tv.m3u', 'epg.xml']:
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

        if not m3u_path.exists():
            return jsonify({'error': 'M3U file not found'}), 404

        # Parse M3U file to extract groups and channels
        groups = defaultdict(list)
        current_channel = None
        total_channels = 0

        with open(m3u_path, 'r', encoding='utf-8') as f:
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

        # Convert to list of groups with channels
        group_list = [
            {
                'name': group_name,
                'channels': channels,
                'channel_count': len(channels),
                'visible': True  # Default visibility state
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
        
        # Paths for original and temporary files
        original_m3u_path = playlist_dir / 'tv.m3u'
        temp_m3u_path = playlist_dir / 'temp.m3u'
        backup_m3u_path = playlist_dir / 'tv.m3u.backup'

        data = request.json
        if not data or 'groups' not in data:
            return jsonify({'error': 'Invalid data format'}), 400

        # Create new M3U content
        try:
            with open(temp_m3u_path, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
                for group in data['groups']:
                    if group.get('visible', True):  # Only include visible groups
                        for channel in group.get('channels', []):
                            if channel.get('visible', True):  # Only include visible channels
                                extinf = channel.get('extinf', '')
                                url = channel.get('url', '')
                                if extinf and url:
                                    f.write(f"{extinf}\n")
                                    f.write(f"{url}\n")

            # Backup original file if it exists
            if original_m3u_path.exists():
                shutil.copy2(original_m3u_path, backup_m3u_path)

            # Replace original with new version
            shutil.move(temp_m3u_path, original_m3u_path)

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


@app.route('/playlist/<int:user_id>/<path:playlist_name>/download', methods=['POST'])
def download_playlist(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        # Get the playlist from the database
        playlist = Playlist.query.filter_by(user_id=user_id, name=playlist_name).first()
        if not playlist:
            return jsonify({'error': 'Playlist not found'}), 404

        data = request.json
        if not data or 'groups' not in data:
            return jsonify({'error': 'Invalid data format'}), 400

        # Create M3U content
        m3u_content = "#EXTM3U\n"
        for group in data['groups']:
            if group.get('visible', True):
                for channel in group.get('channels', []):
                    if channel.get('visible', True):
                        m3u_content += f"{channel['extinf']}\n"
                        m3u_content += f"{channel['url']}\n"

        response = make_response(m3u_content)
        response.headers['Content-Type'] = 'application/x-mpegurl'
        response.headers['Content-Disposition'] = f'attachment; filename=edited_{secure_filename(playlist_name)}.m3u'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Error downloading playlist: {str(e)}")
        return jsonify({'error': str(e)}), 500


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