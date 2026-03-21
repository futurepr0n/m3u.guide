import requests
import m3u_epg_editor as editor

server = "http://cf.loyxy.cloud"
username = "0315f725a2a1"
password = "b569016b2e"

def test_direct_m3u():
    url = f"{server}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
    headers = {
        'User-Agent': editor.get_random_user_agent(),
        'Connection': 'close'
    }
    
    print(f"Testing direct M3U download from {url}...")
    try:
        # First try without custom DNS to see standard behavior
        resp = requests.get(url, headers=headers, timeout=20)
        print(f"Standard Response Status: {resp.status_code}")
        if resp.status_code != 200:
            print(f"Content snippet: {resp.text[:200]}")
            
        # Now try with our robust fetcher (which includes DNS)
        editor.setup_custom_dns()
        resp2 = editor.perform_get_with_backups(url, headers, [])
        print(f"Robust Response Status: {resp2.status_code if resp2 else 'None'}")
        if resp2 and resp2.status_code != 200:
             print(f"Robust Content snippet: {resp2.text[:200]}")
             
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_direct_m3u()
