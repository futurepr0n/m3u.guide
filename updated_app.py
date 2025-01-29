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
        self.playlists_dir = self.base_dir / 'playlists'
        self.playlists_dir.mkdir(exist_ok=True)

    def get_user_playlists(self, user_id):
        return Playlist.query.filter_by(user_id=user_id).all()

    def get_user_directory(self, username):
        user_dir = self.playlists_dir / username
        user_dir.mkdir(exist_ok=True)
        return user_dir

    def add_playlist(self, user_id, playlist_data):
        try:
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

            playlist_directory = self.base_dir / str(user_id) / 'playlists' / playlist_name
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
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max file size
    SQLALCHEMY_DATABASE_URI='sqlite:///' + str(BASE_DIR / 'app.db'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False
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
        'user_id': session['user_id'],  # Add this line to include user_id
        'playlists': [{
            'name': p.name,
            'source': p.source,
            'details': p.details,
            'last_sync': p.last_sync.isoformat() if p.last_sync else None,
            'auto_sync': p.auto_sync
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

        # Create playlist directory
        playlist_dir = BASE_DIR / str(user_id) / 'playlists' / secure_filename(name)
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

@app.route('/playlist/<int:user_id>/<path:playlist_name>/analysis/<path:filename>')
def serve_analysis(user_id, playlist_name, filename):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        analysis_path = BASE_DIR / str(user_id) / 'playlists' / secure_filename(playlist_name) / 'analysis' / secure_filename(filename)
        if not analysis_path.exists():
            return jsonify({'error': 'Resource not found'}), 404

        return send_from_directory(analysis_path.parent, filename)
    except Exception as e:
        app.logger.error(f"Error serving analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500
    

@app.route('/<int:user_id>/playlists/<path:playlist_name>/analysis/<path:filename>')
def serve_analysis_matched(user_id, playlist_name):
    if 'user_id' not in session or session['user_id'] != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        analysis_path = BASE_DIR / str(user_id) / 'playlists' / secure_filename(playlist_name) / 'analysis' / secure_filename(filename)
        if not analysis_path.exists():
            return jsonify({'error': 'Analysis not found'}), 404
            
        return render_template('content_analysis_matched.html', user_id=user_id, playlist_name=playlist_name)
    except Exception as e:
        app.logger.error(f"Error serving analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500

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

        playlist_dir = BASE_DIR / str(user_id) / 'playlists' / secure_filename(playlist_name)
        m3u_path = playlist_dir / 'tv.m3u'
        epg_path = playlist_dir / 'epg.xml'
        analysis_dir = playlist_dir / 'analysis'
        analysis_dir.mkdir(exist_ok=True)

        # Use absolute path to the analyzer script
        analyzer_script = BASE_DIR / 'm3u_analyzer_beefy.py'

        if not analyzer_script.exists():
            return jsonify({'error': 'Analyzer script not found'}), 500

        if not (m3u_path.exists() and epg_path.exists()):
            return jsonify({'error': 'Required files not found for analysis'}), 400

        # Run analyzer script using absolute path
        result = subprocess.run(
            ['python3', str(analyzer_script), str(m3u_path), str(epg_path)],
            cwd=str(analysis_dir),
            capture_output=True,
            text=True,
            check=True
        )
        
        # Check if analysis file was generated
        analysis_file = analysis_dir / 'content_analysis_matched.html'
        if not analysis_file.exists():
            return jsonify({'error': 'Analysis file was not generated'}), 500
            
        return jsonify({
            'message': 'Analysis completed successfully',
            'analysis_url': f'/{user_id}/playlist/{playlist_name}/analysis'
        })

    except subprocess.CalledProcessError as e:
        app.logger.error(f"Analysis script error: {e.stderr}")
        return jsonify({'error': 'Analysis script failed'}), 500
    except Exception as e:
        app.logger.error(f"Error analyzing playlist: {str(e)}")
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
        raise