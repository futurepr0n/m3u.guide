"""Seed the retained private fixture as a disposable local Jellyfin account."""

from pathlib import Path
import os
import shutil

from app import app, db, playlist_manager
from models import Playlist, User


USERNAME = os.getenv("M3UGUIDE_DEV_USERNAME", "jellyfin-dev")
PASSWORD = os.getenv("M3UGUIDE_DEV_PASSWORD", "JellyfinDevOnly!2026")
PLAYLIST = "StreamvisionTV"


def link_or_copy(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


with app.app_context():
    user = User.query.filter_by(username=USERNAME).first()
    if user is None:
        user = User(username=USERNAME, email="jellyfin-dev@localhost.invalid")
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
    else:
        user.set_password(PASSWORD)

    playlist = Playlist.query.filter_by(user_id=user.id, name=PLAYLIST).first()
    if playlist is None:
        playlist = Playlist(name=PLAYLIST, source="local-jellyfin-fixture", user_id=user.id)
        db.session.add(playlist)
    db.session.commit()

    fixture = Path(__file__).parent / "testdata" / "private" / PLAYLIST
    destination = playlist_manager.get_playlist_path(user.id, PLAYLIST)
    destination.mkdir(parents=True, exist_ok=True)
    link_or_copy(fixture / "tv.m3u", destination / "tv.m3u")
    link_or_copy(fixture / "epg.xml", destination / "epg.xml")

    print(f"Server: http://127.0.0.1:5000")
    print(f"Username: {USERNAME}")
    print(f"Password: {PASSWORD}")
    print(f"Playlist: {PLAYLIST}")
