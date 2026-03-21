import requests
import json

server = "http://cf.loyxy.cloud"
username = "0315f725a2a1"
password = "b569016b2e"

def test_xtream():
    base_url = f"{server}/player_api.php?username={username}&password={password}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    actions = ["get_live_categories", "get_live_streams", "get_vod_categories", "get_vod_streams"]
    
    for action in actions:
        url = f"{base_url}&action={action}"
        print(f"Testing {action}...")
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    print(f"Count: {len(data)}")
                except:
                    print("Data is not JSON")
                    print(resp.text[:200])
            else:
                print(resp.text[:200])
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_xtream()
