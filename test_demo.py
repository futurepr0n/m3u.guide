#!/usr/bin/env python3
"""
Simple test script to verify the demo route functionality
"""

import os
import sys
from app import app

def test_demo_route():
    """Test that the demo route exists and responds"""
    with app.test_client() as client:
        # Test without login (should redirect)
        response = client.get('/demo/enhanced/1/my-playlist')
        print(f"Demo route without login: {response.status_code}")
        
        # Test that route exists (not 404)
        if response.status_code == 302:  # Redirect to login
            print("✅ Demo route exists and redirects to login as expected")
        elif response.status_code == 404:
            print("❌ Demo route not found")
        else:
            print(f"Demo route status: {response.status_code}")

def test_static_files():
    """Test that our new static files exist"""
    js_file = 'static/js/content-collapse.js'
    css_file = 'static/css/content-collapse.css'
    template_file = 'templates/demo_content_analysis.html'
    
    files_to_check = [js_file, css_file, template_file]
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            print(f"✅ {file_path} exists")
        else:
            print(f"❌ {file_path} missing")

def check_analysis_data():
    """Check if we have sample analysis data to test with"""
    analysis_path = 'static/playlists/1/my-playlist/analysis/'
    
    if os.path.exists(analysis_path):
        files = os.listdir(analysis_path)
        print(f"✅ Analysis directory exists with {len(files)} files:")
        for file in files:
            print(f"   - {file}")
    else:
        print("❌ No analysis data found - demo will show 404")

if __name__ == '__main__':
    print("🧪 Testing Demo Implementation")
    print("=" * 40)
    
    test_demo_route()
    print()
    
    print("📁 Checking static files:")
    test_static_files()
    print()
    
    print("📊 Checking analysis data:")
    check_analysis_data()
    print()
    
    print("🚀 Demo implementation test complete!")
    print("Next steps:")
    print("1. Start the application: python3 app.py")
    print("2. Navigate to: http://localhost:4444")
    print("3. Login and click '🚀 Enhanced Demo' button")