import requests
import time

def test_headers():
    username = "28934426dea8"
    password = "9f166fb0fb"
    # Using one of the backups that returned 884
    hosts = ["741125.me", "streamvision22.online", "cf.loxyx.xyz"]
    
    path = f"/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
    
    ua_list = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'VLC/3.0.18 LibVLC/3.0.18',
        'IPTVSmartersPlayer',
        'TiviMate/4.7.0 (Linux; Android 11)',
        'OTT-Play/1.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1'
    ]

    for host in hosts:
        for ua in ua_list:
            url = f"http://{host}{path}"
            headers = {
                'User-Agent': ua,
                'Accept': '*/*',
                'Connection': 'keep-alive',
            }
            # Some services require Host header to match if behind a proxy
            # requests handles this by default but we can be explicit
            
            print(f"Testing Host: {host} | UA: {ua[:30]}...")
            try:
                response = requests.get(url, headers=headers, timeout=10, stream=True)
                print(f"  Status: {response.status_code}")
                if response.status_code == 200:
                    print(f"  ✅ SUCCESS with UA: {ua}")
                    response.close()
                    return host, ua
                response.close()
            except Exception as e:
                print(f"  ❌ Error: {e}")
            time.sleep(1) # Small delay to avoid triggering rate limit
        print("-" * 30)
    
    return None

if __name__ == "__main__":
    result = test_headers()
    if result:
        host, ua = result
        print(f"\nSUCCESS! Working combination: Host={host}, UA={ua}")
    else:
        print("\nAll combinations failed.")
