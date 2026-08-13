# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import hashlib

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    stream_token = db.Column(db.String(32), unique=True, nullable=False, default=lambda: secrets.token_hex(16))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    playlists = db.relationship('Playlist', backref='user', lazy=True, cascade='all, delete-orphan')
    integration_tokens = db.relationship('IntegrationToken', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class IntegrationToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, default='Jellyfin')
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    token_prefix = db.Column(db.String(12), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, user, name='Jellyfin'):
        token = secrets.token_urlsafe(32)
        record = cls(
            user_id=user.id,
            name=name[:100] or 'Jellyfin',
            token_hash=cls.digest(token),
            token_prefix=token[:12],
        )
        db.session.add(record)
        db.session.commit()
        return record, token

class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    source = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_sync = db.Column(db.DateTime)
    auto_sync = db.Column(db.Boolean, default=False)
    
    # Analysis results
    total_channels = db.Column(db.Integer, default=0)
    total_epg_matches = db.Column(db.Integer, default=0)
    total_movies = db.Column(db.Integer, default=0)
    total_series = db.Column(db.Integer, default=0)
    total_unmatched = db.Column(db.Integer, default=0)
    m3u_editor_command = db.Column(db.String(1000))
    
    # Store paths and credentials as JSON
    details = db.Column(db.JSON)
    
    # Relationships
    groups = db.relationship('Group', backref='playlist', lazy=True, cascade='all, delete-orphan')

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'), nullable=False)
    sort_order = db.Column(db.Integer)
    visible = db.Column(db.Boolean, default=True)
    
    # Relationship
    channels = db.relationship('Channel', backref='group', lazy=True, cascade='all, delete-orphan')

class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    extinf = db.Column(db.Text)  # Store original EXTINF line
    url = db.Column(db.Text)
    tvg_id = db.Column(db.String(200))
    visible = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer)

def init_db(app):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
