from pathlib import Path
import json
import os
import sys

# Add current dir to path to import app and m3u_epg_editor
sys.path.append(os.getcwd())

import m3u_epg_editor as editor
from app import process_xtream_api

server = "http://cf.loyxy.cloud"
username = "0315f725a2a1"
password = "b569016b2e"

def test_full_process():
    form_data = {
        'server': server,
        'username': username,
        'password': password,
        'include_vod': 'true',
        'include_series': 'false', # Only VOD for now to see volume
        'include_proxy': 'false'
    }
    
    m3u_path = Path('test_output.m3u')
    epg_path = Path('test_epg.xml')
    details = {}
    
    print("Starting full Xtream API process (with VOD)...")
    import time
    start = time.time()
    
    # We need a mock request context for host_url
    from flask import Flask, request
    app = Flask(__name__)
    with app.test_request_context(base_url='http://localhost:4444'):
        success = process_xtream_api(form_data, m3u_path, epg_path, details)
    
    end = time.time()
    print(f"Process success: {success}")
    print(f"Time taken: {end - start:.2f}s")
    
    if m3u_path.exists():
        size = m3u_path.stat().st_size
        print(f"M3U size: {size / 1024 / 1024:.2f} MB")
        with open(m3u_path, 'r') as f:
            lines = f.readlines()
            print(f"M3U line count: {len(lines)}")
            print("First 10 lines:")
            print("".join(lines[:10]))
            
if __name__ == "__main__":
    test_full_process()
