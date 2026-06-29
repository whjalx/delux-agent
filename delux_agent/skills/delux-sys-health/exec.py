#!/usr/bin/env python3
"""System health report — production-grade JSON output."""
import json
import os
import platform
import re
import subprocess
import sys
import time


def _read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except (PermissionError, FileNotFoundError, OSError, UnicodeDecodeError):
        return None


def _read_proc_meminfo():
    text = _read_file("/proc/meminfo")
    if text is None:
        return {}
    mem = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            try:
                # kernel reports in kB
                mem[key] = int(parts[1]) * 1024
            except (ValueError, IndexError):
                pass
    return mem


def _cpu_load():
    try:
        if hasattr(os, "getloadavg"):
            return list(os.getloadavg())
        # fallback via /proc/loadavg
        text = _read_file("/proc/loadavg")
        if text:
            parts = text.split()
            return [float(parts[0]), float(parts[1]), float(parts[2])]
        return None
    except Exception:
        return None


def _memory():
    info = {"total": None, "free": None, "available": None, "swap_total": None, "swap_free": None}
    system = platform.system()

    if system == "Linux":
        m = _read_proc_meminfo()
        if m:
            info["total"] = m.get("MemTotal")
            info["free"] = m.get("MemFree")
            info["available"] = m.get("MemAvailable")
            info["swap_total"] = m.get("SwapTotal")
            info["swap_free"] = m.get("SwapFree")
            info["used"] = (info["total"] - info["available"]) if (info["total"] and info["available"]) else None
        return info

    if system == "Darwin":
        try:
            sz = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                timeout=5, encoding="utf-8", errors="replace")
            if sz.returncode == 0:
                info["total"] = int(sz.stdout.strip())
        except Exception:
            pass
        return info

    # Fallback: try free command
    try:
        out = subprocess.run(["free", "-b"], capture_output=True, text=True,
                            timeout=5, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            for line in out.stdout.splitlines():
                if line.startswith("Mem:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        info["total"] = int(parts[1])
                        info["used"] = int(parts[2])
                        info["free"] = int(parts[3]) if len(parts) > 3 else None
                if line.startswith("Swap:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        info["swap_total"] = int(parts[1])
                        info["swap_free"] = int(parts[3]) if len(parts) > 3 else None
    except Exception:
        pass
    return info


def _disk_usage():
    mounts = []
    # Linux
    text = _read_file("/proc/mounts")
    if text:
        seen = set()
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 2 or not parts[1].startswith("/"):
                continue
            mp = parts[1]
            if mp in seen:
                continue
            seen.add(mp)
            try:
                usage = os.statvfs(mp)
                total = usage.f_frsize * usage.f_blocks
                free = usage.f_frsize * usage.f_bavail
                used = total - free
                pct = round(used / total * 100, 1) if total > 0 else 0
                mounts.append({
                    "mount": mp,
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "percent_used": pct,
                })
            except (PermissionError, OSError, FileNotFoundError):
                pass
        return mounts

    # Fallback: macOS / other
    try:
        out = subprocess.run(["df", "-P", "-B1"], capture_output=True, text=True,
                            timeout=5, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            for line in out.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 6:
                    continue
                try:
                    total = int(parts[1])
                    used = int(parts[2])
                    free = int(parts[3])
                    pct = round(used / total * 100, 1) if total > 0 else 0
                    mounts.append({
                        "mount": parts[5],
                        "total_bytes": total,
                        "used_bytes": used,
                        "free_bytes": free,
                        "percent_used": pct,
                    })
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass
    return mounts


def _interfaces():
    ifaces = []
    # /sys/class/net
    if os.path.isdir("/sys/class/net"):
        try:
            for name in sorted(os.listdir("/sys/class/net")):
                ifaces.append(name)
        except PermissionError:
            pass
        return ifaces
    # fallback
    try:
        out = subprocess.run(["ip", "-brief", "address", "show"], capture_output=True, text=True,
                            timeout=5, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            for line in out.stdout.strip().splitlines():
                if line:
                    ifaces.append(line.split()[0] if line.split() else line.strip())
            return ifaces
    except Exception:
        pass
    try:
        out = subprocess.run(["ifconfig", "-l"], capture_output=True, text=True,
                            timeout=5, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            for tok in out.stdout.strip().split():
                ifaces.append(tok)
            return ifaces
    except Exception:
        pass
    return ifaces


def _process_count():
    # Linux
    if os.path.isdir("/proc"):
        try:
            count = 0
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    count += 1
            return count
        except PermissionError:
            pass
    # fallback
    for cmd in (["ps", "-e"], ["ps", "aux"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=5, encoding="utf-8", errors="replace")
            if out.returncode == 0:
                return len(out.stdout.strip().splitlines()) - 1  # minus header
        except Exception:
            continue
    return None


def _uptime():
    text = _read_file("/proc/uptime")
    if text:
        try:
            return float(text.split()[0])
        except (ValueError, IndexError):
            pass
    # fallback
    try:
        out = subprocess.run(["uptime", "-p"], capture_output=True, text=True,
                            timeout=5, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True,
                            timeout=5, encoding="utf-8", errors="replace")
        if out.returncode == 0:
            # Extract sec = ... from { sec = 123456, ... }
            m = re.search(r"sec\s*=\s*(\d+)", out.stdout)
            if m:
                boot_ts = int(m.group(1))
                now = time.time()
                return max(0, now - boot_ts)
    except Exception:
        pass
    return None


def main():
    try:
        data = {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "platform": sys.platform,
            },
            "cpu": {
                "load_average": _cpu_load(),
            },
            "memory": _memory(),
            "disk": _disk_usage(),
            "network": {
                "interfaces": _interfaces(),
            },
            "processes": {
                "count": _process_count(),
            },
            "uptime": _uptime(),
        }
        print(json.dumps({"status": "ok", "data": data}))
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
