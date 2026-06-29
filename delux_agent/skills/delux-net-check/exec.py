#!/usr/bin/env python3
"""Network diagnostics — production-grade with JSON output."""
import json
import os
import socket
import subprocess
import sys
import time
import shutil

_TIMEOUT_PING = 3
_TIMEOUT_DNS = 3
_TIMEOUT_CURL = 5
_PING_TARGETS = [
    ("8.8.8.8", "Google DNS"),
    ("1.1.1.1", "Cloudflare DNS"),
    ("github.com", "GitHub"),
]


def _ping(host):
    cmd = ["ping", "-c", "1", "-W", str(_TIMEOUT_PING), host]
    t0 = time.monotonic()
    try:
        # prefer socket type checks on ipv4/ipv6
        addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        is_v6 = all(fam == socket.AF_INET6 for fam, *_ in addrs)
        if is_v6 and shutil.which("ping6"):
            cmd = ["ping6", "-c", "1", "-W", str(_TIMEOUT_PING), host]
    except Exception:
        pass
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=_TIMEOUT_PING + 2)
        latency = round((time.monotonic() - t0) * 1000, 2)
        return True, latency
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, PermissionError, OSError):
        latency = round((time.monotonic() - t0) * 1000, 2)
        return False, latency


def _dns_resolve(host):
    t0 = time.monotonic()
    old_to = socket.getdefaulttimeout()
    socket.setdefaulttimeout(_TIMEOUT_DNS)
    try:
        socket.gethostbyname(host)
        latency = round((time.monotonic() - t0) * 1000, 2)
        return True, latency
    except (socket.gaierror, socket.herror, OSError):
        latency = round((time.monotonic() - t0) * 1000, 2)
        return False, latency
    finally:
        socket.setdefaulttimeout(old_to)


def _public_ip():
    if not shutil.which("curl"):
        return None, "curl not installed"
    try:
        res = subprocess.run(
            ["curl", "-s", "--max-time", str(_TIMEOUT_CURL), "ifconfig.me"],
            capture_output=True, text=True, timeout=_TIMEOUT_CURL + 3,
            encoding="utf-8", errors="replace",
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip(), None
        return None, f"curl exit {res.returncode}"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as exc:
        return None, str(exc)


def _validate_args():
    """No extra args needed; accept optional optional positional to ignore."""
    pass


def main():
    try:
        _validate_args()
    except (ValueError, TypeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        sys.exit(1)

    data = {
        "os": sys.platform,
        "checks": {},
    }

    # --- localhost ---
    ok, lat = _ping("127.0.0.1")
    data["checks"]["localhost_ping"] = {"ok": ok, "latency_ms": lat if ok else None, "error": None if ok else "unreachable"}

    # Fallback: if ping not available, try TCP connect to 127.0.0.1:22
    if not ok and not shutil.which("ping"):
        data["checks"]["localhost_ping"]["error"] = "ping not available"

    # --- DNS ---
    ok, lat = _dns_resolve("google.com")
    data["checks"]["dns_resolution"] = {"ok": ok, "latency_ms": lat if ok else None, "target": "google.com", "error": None if ok else "resolution failed"}

    # --- External ping ---
    ext_results = {}
    for host, name in _PING_TARGETS:
        ok, lat = _ping(host)
        ext_results[name] = {"host": host, "ok": ok, "latency_ms": lat if ok else None}
    data["checks"]["external_ping"] = ext_results

    # --- Public IP ---
    ip, err = _public_ip()
    data["checks"]["public_ip"] = {"ok": ip is not None, "ip": ip, "error": err}

    data["summary"] = {
        "localhost": data["checks"]["localhost_ping"]["ok"],
        "dns": data["checks"]["dns_resolution"]["ok"],
        "external_reachable": any(v["ok"] for v in ext_results.values()),
    }

    print(json.dumps({"status": "ok", "data": data}))


if __name__ == "__main__":
    main()
