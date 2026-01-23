import requests
import time
import socket
import dns.resolver
import ipaddress
import random
import json

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
                        print(f"  [DNS] Resolved {host}")
            except Exception as e:
                print(f"  [DNS] Resolution failed: {e}")
        return original_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = new_getaddrinfo

def get_random_user_agent():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "VLC/3.0.20 LibVLC/3.0.20",
    ]
    return random.choice(user_agents)

def test_player_api():
    setup_custom_dns()
    username = "28934426dea8"
    password = "9f166fb0fb"
    hosts = ["cf.loxyx.xyz", "streamvision22.online", "741125.me"]
    
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json',
        'Connection': 'close',
    }

    for host in hosts:
        url = f"http://{host}/player_api.php?username={username}&password={password}"
        print(f"Testing URL: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=15)
            print(f"  Status Code: {response.status_code}")
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "user_info" in data:
                        print(f"  ✅ SUCCESS! Found user_info for {host}")
                        # print(f"  Data: {json.dumps(data, indent=2)}")
                        return host
                    else:
                        print(f"  ⚠️  Status 200 but no user_info: {data}")
                except Exception as e:
                    print(f"  ⚠️  Status 200 but failed to parse JSON: {e}")
                    print(f"  Content Preview: {response.text[:200]}")
            else:
                print(f"  ❌ FAILED with status code {response.status_code}")
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
        print("-" * 20)
    
    return None

if __name__ == "__main__":
    test_player_api()
