import requests
import time
import socket
import dns.resolver
import ipaddress
import random
from urllib.parse import urlparse, parse_qs

def setup_custom_dns():
    dns_servers = ["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4", "9.9.9.9"]
    custom_resolver = dns.resolver.Resolver()
    custom_resolver.nameservers = dns_servers
    original_getaddrinfo = socket.getaddrinfo

    def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host:
            try:
                try:
                    ipaddress.ip_address(host)
                    return original_getaddrinfo(host, port, family, type, proto, flags)
                except ValueError:
                    try:
                        result = original_getaddrinfo(host, port, family, type, proto, flags)
                        return result
                    except Exception:
                        answers = custom_resolver.resolve(host)
                        host = str(answers[0])
            except Exception:
                pass
        return original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = new_getaddrinfo

def get_random_user_agent():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ]
    return random.choice(user_agents)

def get_m3u_from_api(url, headers):
    print(f"  [API] Attempting fallback for: {url}")
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        username = params.get('username', [None])[0]
        password = params.get('password', [None])[0]
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # 1. Categories
        cat_url = f"{base_url}/player_api.php?username={username}&password={password}&action=get_live_categories"
        cat_resp = requests.get(cat_url, headers=headers, timeout=15)
        cat_map = {c['category_id']: c['category_name'] for c in cat_resp.json()}

        # 2. Streams
        stream_url = f"{base_url}/player_api.php?username={username}&password={password}&action=get_live_streams"
        stream_resp = requests.get(stream_url, headers=headers, timeout=20)
        streams = stream_resp.json()

        # 3. M3U Construction
        lines = ["#EXTM3U"]
        for s in streams[:5]: # Just preview first 5
            name = s.get('name')
            group = cat_map.get(s.get('category_id'), "Uncategorized")
            lines.append(f'#EXTINF:-1 group-title="{group}",{name}')
            lines.append(f"{base_url}/live/{username}/{password}/{s.get('stream_id')}.ts")
        
        return "\n".join(lines)
    except Exception as e:
        print(f"  [API] Fallback failed: {e}")
        return None

def test_connectivity():
    setup_custom_dns()
    username = "28934426dea8"
    password = "9f166fb0fb"
    hosts = ["cf.loxyx.xyz", "streamvision22.online"]
    
    path = f"/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
    
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': '*/*',
        'Connection': 'close',
    }

    for host in hosts:
        url = f"http://{host}{path}"
        print(f"Testing Host: {host}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"  Direct Status: {response.status_code}")
            
            if response.status_code == 884 or response.status_code != 200:
                print(f"  ⚠️ Direct download failed ({response.status_code}), trying API fallback...")
                m3u_content = get_m3u_from_api(url, headers)
                if m3u_content:
                    print(f"  ✅ API FALLBACK SUCCESS!")
                    print(f"  Preview:\n{m3u_content}")
                    return True
        except Exception as e:
            print(f"  ❌ Error: {e}")
        print("-" * 20)
    
    return False

if __name__ == "__main__":
    test_connectivity()
