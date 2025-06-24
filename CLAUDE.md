# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**m3u.guide** is a comprehensive Flask-based IPTV/M3U playlist management system that provides users with advanced tools to manage, analyze, optimize, and edit IPTV playlists. The application serves as a complete solution for IPTV content management with sophisticated analysis capabilities.

### Core Capabilities
- **Multi-source Playlist Processing**: API Line, M3U URL, and file upload support
- **Advanced Content Analysis**: Categorizes content into movies, series, live TV with EPG matching
- **Playlist Optimization**: Uses m3u-epg-editor tool for automated playlist cleaning
- **Interactive Playlist Editor**: Real-time channel/group visibility management
- **Content Analysis Reports**: Detailed HTML reports with VLC integration and URL copying
- **User Management**: Secure authentication with isolated user workspaces

## System Architecture

### Backend Framework (Flask)
- **app.py**: Main Flask application (915 lines) with comprehensive routing and PlaylistManager class
- **models.py**: SQLAlchemy ORM models with complete relationship management
- **auth.py**: Authentication blueprint with registration, login, logout functionality
- **m3u_analyzer_beefy.py**: Original content analysis engine
- **m3u_analyzer_beefy-new.py**: Enhanced analyzer with VLC integration and copy URL features
- **m3u-epg-editor-py3.py**: External optimization tool for playlist processing

### Frontend Components
- **static/js/main.js**: Dashboard management, playlist operations, content analysis navigation
- **static/js/playlist-editor.js**: Dual-panel editor with real-time filtering and editing
- **static/css/styles.css**: Comprehensive styling for all application components
- **templates/**: Jinja2 templates (index.html, playlist_editor.html, auth pages, video player)

### Database Architecture (SQLAlchemy)
```
User (id, username, email, password_hash, created_at)
  ↓ (1:many)
Playlist (id, name, source, user_id, total_channels, total_movies, etc.)
  ↓ (1:many)  
Group (id, name, playlist_id, sort_order, visible)
  ↓ (1:many)
Channel (id, name, group_id, extinf, url, tvg_id, visible, sort_order)
```

### File Storage Structure
```
static/playlists/{user_id}/{playlist_name}/
├── tv.m3u                    # Original M3U playlist
├── epg.xml                   # EPG data file
├── analysis/                 # Content analysis reports
│   ├── content_analysis_matched.html
│   ├── content_analysis_movies.html
│   ├── content_analysis_series.html
│   ├── content_analysis_unmatched.html
│   ├── content_analysis_unmatched_no_tvg.html
│   ├── command.json          # Optimization commands and statistics
│   └── index.html
└── optimized/               # m3u-epg-editor output
    ├── cleaned.m3u8
    ├── cleaned.xml
    ├── cleaned.channels.txt
    └── original.channels.txt
```

## Development Commands

### Local Development
```bash
# Setup and run locally
./startup_app.sh

# Manual setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

### Docker Development
```bash
# Build and run with Docker Compose
docker-compose up --build

# Development mode (port 4444)
docker-compose -f compose-dev.yaml up
```

### Database Operations
```bash
# Initialize database
python3 -c "from app import app; from models import db; app.app_context().push(); db.create_all()"
```

## Core Application Components

### 1. PlaylistManager Class (app.py:36-99)
Central orchestrator for playlist operations:
- **User Directory Management**: Creates isolated storage for each user
- **Playlist CRUD Operations**: Add, delete, and retrieve user playlists
- **File Path Resolution**: Secure filename handling and path generation
- **Database Integration**: Coordinates with SQLAlchemy models

### 2. Content Analysis System

#### m3u_analyzer_beefy.py (Original Analyzer)
- **M3U Parsing**: Extracts channels, groups, TVG IDs, logos from EXTINF lines
- **EPG Matching**: Matches channels with EPG data using tvg-id attributes
- **Content Categorization**: Identifies movies, series, live TV based on URL patterns
- **Report Generation**: Creates static HTML analysis reports
- **Statistics Calculation**: Provides detailed content breakdowns

#### m3u_analyzer_beefy-new.py (Enhanced Analyzer)
Enhanced version with additional features:
- **VLC Integration**: Multi-platform VLC launch buttons (Desktop, iOS, Android)
- **URL Copying**: Copy stream URLs to clipboard functionality
- **Series Management**: Advanced series/season/episode organization
- **Interactive Elements**: Collapsible series sections with episode tables
- **Action Buttons**: Download, Watch, VLC launchers, Copy URL per content item

### 3. Optimization System (m3u-epg-editor Integration)
Leverages external m3u-epg-editor-py3.py tool:
- **Channel Filtering**: Keeps only EPG-matched channels based on analysis results
- **Group Management**: Supports group inclusion/exclusion with -g parameter
- **File Optimization**: Creates cleaned M3U and XML files in optimized/ directory
- **Command Generation**: Auto-generates optimization commands from analysis data
- **Format Support**: Handles various M3U formats and EPG structures

### 4. Interactive Playlist Editor (Dual-Panel Interface)
**Groups Panel** (Left Side):
- Lists all channel groups with item counts
- Real-time visibility toggles (eye icons)
- Group renaming functionality
- Bulk operations (enable/disable all groups)
- Group selection for channel browsing

**Channels Panel** (Right Side):
- Displays channels for selected group
- Individual channel visibility controls
- Channel renaming capabilities
- Logo display with fallback handling
- Bulk channel operations

**Features**:
- **Real-time Statistics**: Updates visible channel counts dynamically
- **Atomic Save Operations**: Creates backups before modifications
- **Change Tracking**: Visual indicators for unsaved changes
- **Download Functionality**: Export edited playlists as M3U files

### 5. Authentication & Security System

#### User Management (auth.py)
- **Registration**: Username/email uniqueness validation
- **Login/Logout**: Session-based authentication
- **Password Security**: Werkzeug password hashing
- **Error Handling**: Graceful failure management

#### Security Features
- **Session Management**: Flask-Session for secure user sessions
- **File Isolation**: User-specific directories prevent cross-user access
- **Secure Filenames**: werkzeug.utils.secure_filename for upload safety
- **Input Validation**: Form data validation and sanitization

### 6. Database Models & Relationships

#### User Model (models.py:9-21)
```python
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    playlists = db.relationship('Playlist', backref='user', lazy=True, cascade='all, delete-orphan')
```

#### Playlist Model (models.py:23-44)
```python
class Playlist(db.Model):
    # Core fields
    name, source, user_id, created_at, last_sync, auto_sync
    
    # Analysis results (populated by analyzer)
    total_channels, total_epg_matches, total_movies, total_series, total_unmatched
    
    # Optimization data
    m3u_editor_command  # Auto-generated optimization command
    details             # JSON field for API credentials and file paths
```

#### Group & Channel Models (models.py:46-65)
Support for hierarchical playlist structure with visibility controls and sorting.

### 7. API Endpoints & Routing

#### Core Application Routes
- **`/`**: Main dashboard (redirects to login if not authenticated)
- **`/get-playlists`**: JSON API returning user's playlists with statistics
- **`/process-playlist`**: Handles multi-source playlist creation and auto-analysis
- **`/analyze-playlist`**: Triggers content analysis and report generation
- **`/optimize-playlist`**: Executes m3u-epg-editor optimization
- **`/delete-playlist`**: Removes playlist and associated files

#### Content Analysis Routes
- **`/static/playlists/{user_id}/{playlist_name}/analysis/{filename}`**: Serves analysis HTML reports
- **`/static/playlists/{user_id}/{playlist_name}/analysis/`**: Default analysis landing page
- **`/watch_video?url={encoded_url}`**: Internal video player for content streaming

#### Playlist Editor Routes
- **`/playlist/{user_id}/{playlist_name}/edit`**: Loads dual-panel playlist editor
- **`/playlist/{user_id}/{playlist_name}/save`**: Saves editor changes with atomic operations
- **`/playlist/{user_id}/{playlist_name}/download`**: Downloads edited playlist as M3U

#### File Serving Routes
- **`/static/playlists/{user_id}/{playlist_name}/{filetype}`**: Serves M3U and EPG files with CORS headers
- **`/static/playlists/{user_id}/{playlist_name}/{filename}`**: General file serving with authentication

## Configuration

### Environment Variables
- FLASK_SECRET_KEY: Session encryption key
- FLASK_ENV: development/production
- FLASK_DEBUG: Debug mode toggle

### Database
- SQLite database (app.db) in project root
- Automatic initialization on first run
- Models use SQLAlchemy with relationship cascades

## Application Workflow

### Main Dashboard (index.html)
- Displays table of all user playlists with statistics
- Shows channels, EPG matches, movies, series, and unmatched counts
- Action buttons for each playlist:
  - **Edit**: Opens playlist editor for channel/group management
  - **Delete**: Removes playlist and associated files
  - **Process**: Re-processes playlist from original source
  - **Analyze**: Runs content analysis and generates reports
  - **Content Analysis**: Views generated HTML analysis reports
  - **Optimize**: Creates optimized playlist using m3u-epg-editor

### Content Analysis Workflow
1. User uploads/creates playlist (M3U + EPG files)
2. Runs analysis to categorize content and match EPG data
3. Generates detailed HTML reports showing:
   - Matched channels with EPG data
   - Movies organized by groups
   - Series with season/episode structure
   - Unmatched content requiring manual review

### Optimize Workflow
1. Requires completed analysis first
2. Uses generated optimization command from analysis
3. Filters playlist to keep only EPG-matched channels
4. Creates cleaned, optimized M3U and XML files
5. Outputs ready-to-use playlist files

### Edit Workflow
1. Opens dual-panel editor interface
2. User toggles visibility of groups/channels
3. Rename groups and channels as needed
4. Save changes updates the original M3U file
5. Download creates a copy of the edited playlist

## Technology Stack & Dependencies

### Backend Dependencies (requirements.txt)
```
Flask==2.2.0                 # Web framework
Flask-Session==0.5.0         # Session management
Flask-SQLAlchemy==3.0.2      # ORM and database integration
requests==2.28.1             # HTTP client for M3U/EPG downloads
Werkzeug==2.2.0             # WSGI utilities and security
python-dotenv==0.19.0       # Environment variable management
lxml==5.3.0                 # XML parsing for EPG files
python_dateutil==2.9.0.post0 # Date/time utilities
tzlocal==4.3.1              # Timezone handling
```

### Frontend Technologies
- **JavaScript ES6+**: Modern JavaScript for dynamic functionality
- **CSS3**: Responsive design with Grid and Flexbox layouts
- **Font Awesome**: Icon library for UI elements
- **Vanilla JavaScript**: No heavy frameworks, optimized for performance

### Database & Storage
- **SQLite**: Lightweight database for user data and playlist metadata
- **File System**: Direct file storage for M3U, EPG, and analysis files
- **JSON**: Configuration and analysis result storage

## Deployment Options

### Local Development (startup_app.sh)
```bash
#!/bin/bash
# Creates virtual environment
# Installs dependencies
# Generates secret key
# Initializes database
# Starts Flask development server on port 4444
```

### Docker Deployment
```dockerfile
FROM python:3.9
# Production-ready container
# Virtual environment setup
# Dependency installation
# Port 5000 exposure
```

#### Docker Compose (docker-compose.yml)
```yaml
version: '3'
services:
  web:
    build: .
    ports: "4444:4444"
    volumes: .:/app
    environment:
      FLASK_ENV=development
      FLASK_DEBUG=1
```

### Production Considerations
- **Reverse Proxy**: Use Nginx for static file serving and SSL termination
- **Database**: Consider PostgreSQL for production deployments
- **File Storage**: Implement cloud storage for large-scale deployments
- **Process Management**: Use Gunicorn with multiple workers
- **Monitoring**: Add application performance monitoring

## Performance Characteristics

### File Processing Capabilities
- **Large Playlists**: Tested with 275,000+ content items
- **Analysis Speed**: ~1-2 seconds per 1,000 channels
- **Memory Usage**: Efficient processing with streaming where possible
- **Storage Requirements**: ~10-50MB per analyzed playlist

### Browser Performance
- **Content Analysis Pages**: Handle 200,000+ DOM elements efficiently
- **Editor Interface**: Real-time updates for 50,000+ channels
- **Image Loading**: Lazy loading prevents performance degradation
- **JavaScript Memory**: Optimized for large dataset manipulation

## Security Architecture

### Authentication Security
- **Password Hashing**: Werkzeug's generate_password_hash with salt
- **Session Management**: Flask-Session with secure session storage
- **User Isolation**: Complete file and data separation between users
- **Input Validation**: Comprehensive sanitization of all user inputs

### File Security
- **Secure Uploads**: werkzeug.utils.secure_filename for all file operations
- **Path Traversal Protection**: Absolute path validation and user directory isolation
- **CORS Headers**: Controlled cross-origin access for M3U/EPG serving
- **Authentication Checks**: User verification for all file access

### Data Protection
- **SQL Injection Prevention**: SQLAlchemy ORM with parameterized queries
- **XSS Protection**: Template escaping and input sanitization
- **Directory Traversal**: Secure file path handling
- **Environment Security**: Secret key management and environment isolation

## Error Handling & Logging

### Application Logging
```python
# Rotating file handler for production
# ERROR level logging for failures
# INFO level for operational events
# DEBUG level for development
```

### Error Recovery
- **Database Rollback**: Automatic transaction rollback on errors
- **File Cleanup**: Orphaned file removal on operation failures
- **Graceful Degradation**: Fallback modes for component failures
- **User Feedback**: Clear error messages without sensitive information

## Maintenance & Operations

### Database Maintenance
```bash
# Backup database
cp app.db app_backup_$(date +%Y%m%d).db

# Initialize fresh database
python3 -c "from app import app; from models import db; app.app_context().push(); db.create_all()"
```

### File System Maintenance
```bash
# Clean up orphaned playlist files
# Monitor disk space usage
# Archive old analysis results
# Compress large M3U files
```

### Performance Monitoring
- **Response Times**: Monitor API endpoint performance
- **Memory Usage**: Track application memory consumption
- **Disk Usage**: Monitor file storage growth
- **User Activity**: Track feature usage patterns

## Integration Capabilities

### External Tool Integration
- **m3u-epg-editor-py3.py**: Advanced playlist optimization
- **VLC Media Player**: Multi-platform content launching
- **External APIs**: Support for IPTV provider APIs
- **EPG Services**: Integration with electronic program guide providers

### API Extensibility
- **RESTful Design**: Clean API structure for future integrations
- **JSON Responses**: Standardized data interchange format
- **Authentication Headers**: Support for API key authentication
- **Webhook Support**: Potential for real-time integrations

## Troubleshooting Guide

### Common Issues

#### Application Won't Start
```bash
# Check Python version (requires 3.7+)
python3 --version

# Verify virtual environment
source venv/bin/activate
which python

# Check dependencies
pip install -r requirements.txt

# Database initialization
python3 -c "from app import app; from models import db; app.app_context().push(); db.create_all()"
```

#### Playlist Processing Failures
- **File Permissions**: Ensure write access to static/playlists directory
- **Disk Space**: Check available storage for large playlists
- **Network Issues**: Verify connectivity for URL-based M3U/EPG sources
- **File Format**: Validate M3U file structure and encoding

#### Content Analysis Issues
- **Missing Analysis Files**: Check m3u_analyzer_beefy.py execution permissions
- **Large Dataset Timeouts**: Increase subprocess timeout for massive playlists
- **Memory Errors**: Monitor system memory during analysis
- **EPG Matching**: Verify EPG file format and tvg-id consistency

#### Editor Performance
- **Large Playlists**: Use browser with sufficient memory
- **JavaScript Errors**: Check browser console for client-side issues
- **Save Failures**: Verify file permissions and disk space
- **UI Responsiveness**: Consider playlist size limitations

### Development Tips
- **Debug Mode**: Enable FLASK_DEBUG=1 for detailed error messages
- **Database Inspection**: Use SQLite browser for data examination
- **Log Analysis**: Monitor logs/app.log for operational insights
- **Performance Profiling**: Use browser dev tools for frontend optimization

## Future Enhancement Opportunities

### Performance Optimizations
- **Database Indexing**: Add indexes for large dataset queries
- **Caching Layer**: Implement Redis for analysis result caching
- **Background Processing**: Use Celery for async analysis tasks
- **CDN Integration**: Offload static asset delivery

### Feature Enhancements
- **Real-time Search**: Implement the content-UI-enhancement.md plan
- **Image Caching**: Deploy the Image-Caching-Plan.md strategy  
- **VLC Integration**: Enhance with VLC-Enhancement.md features
- **Bulk Operations**: Multi-playlist management capabilities

### Scalability Improvements
- **Microservices**: Split analysis engine into separate service
- **Load Balancing**: Multi-instance deployment support
- **Database Scaling**: PostgreSQL with read replicas
- **Container Orchestration**: Kubernetes deployment manifests