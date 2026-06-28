#!/usr/bin/env python3
import socket
import subprocess
import shutil
import time

def check_ping(host):
    cmd = ["ping", "-c", "1", "-W", "2", host]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except:
        return False

def check_dns(host):
    try:
        socket.gethostbyname(host)
        return True
    except:
        return False

def main():
    print("\033[1;32m=== Network Diagnostics ===\033[0m")
    
    # Check Localhost
    print(f"Localhost (127.0.0.1): {'\033[32mOK\033[0m' if check_ping('127.0.0.1') else '\033[31mFAIL\033[0m'}")
    
    # Check DNS
    print(f"DNS Resolution (google.com): {'\033[32mOK\033[0m' if check_dns('google.com') else '\033[31mFAIL\033[0m'}")
    
    # Check External Connectivity
    targets = [
        ("Google (8.8.8.8)", "8.8.8.8"),
        ("Cloudflare (1.1.1.1)", "1.1.1.1"),
        ("Github (github.com)", "github.com"),
    ]
    
    print("\033[1mExternal Connectivity:\033[0m")
    for name, host in targets:
        start = time.time()
        ok = check_ping(host)
        elapsed = (time.time() - start) * 1000
        status = f"\033[32mOK\033[0m ({elapsed:.1f}ms)" if ok else "\033[31mFAIL\033[0m"
        print(f"  {name:25}: {status}")

    # Public IP (using curl if available)
    if shutil.which("curl"):
        try:
            print(f"\033[1mPublic IP:\033[0m ", end="", flush=True)
            res = subprocess.run(["curl", "-s", "--max-time", "3", "ifconfig.me"], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"\033[36m{res.stdout.strip()}\033[0m")
            else:
                print("\033[31mUnknown\033[0m")
        except:
            print("\033[31mUnknown\033[0m")

if __name__ == "__main__":
    main()
