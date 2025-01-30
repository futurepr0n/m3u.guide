# M3U.GUIDE

## What is it?
m3u.guide is an iptv/m3u manager type application which is meant for taking your files and analyzing them, optimizing an epg for only entries found in your m3u, toggling on and off which channels or content you want visible and creating a custom playlist from those selections. This is not affiliated with, but leverages the (m3u-epg-editor)[https://github.com/bebo-dot-dev/m3u-epg-editor] that I found on github. The aim was to create a self hosted replacement for m3u4us because at one point that site went down and then made you have to also use dropbox, the process was a bit brutal and also noone can vet or use or help their project, and this is aimed to be open so anyone can help or make suggestions.

## Installation
To install, you can download the repo and stand up with docker. A simple way is using docker dev environments.
Also feel free to test it out at https://m3u.guide.

#### Security
Our security is built on the following:
- using password hashing (in models.py using generate_password_hash and check_password_hash)
- secure session management with Flask-Session
- CSRF protection through Flask's built-in mechanisms
- `secure_filename` for file operations
