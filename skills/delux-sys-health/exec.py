#!/usr/bin/env python3
import os
import sys
import shutil
import platform
import subprocess

def get_size(bytes, suffix="B"):
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor

def main():
    print("\033[1;36m=== System Health Report ===\033[0m")
    
    # OS Info
    print(f"\033[1mOS:\033[0m {platform.system()} {platform.release()} ({platform.machine()})")
    
    # CPU usage (simple load average)
    if hasattr(os, 'getloadavg'):
        load = os.getloadavg()
        print(f"\033[1mLoad Average:\033[0m {load[0]}, {load[1]}, {load[2]}")
    
    # Memory
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                mem_total = int(lines[0].split()[1]) * 1024
                mem_free = int(lines[1].split()[1]) * 1024
                print(f"\033[1mMemory:\033[0m Total: {get_size(mem_total)}, Free: {get_size(mem_free)}")
        elif platform.system() == "Darwin":
            proc = subprocess.run(["sysctl", "hw.memsize"], capture_output=True, text=True)
            mem_total = int(proc.stdout.split(":")[1].strip())
            print(f"\033[1mMemory:\033[0m Total: {get_size(mem_total)}")
    except Exception as e:
        print(f"\033[1mMemory:\033[0m Could not retrieve ({e})")

    # Disk usage
    total, used, free = shutil.disk_usage("/")
    print(f"\033[1mDisk (/):\033[0m Total: {get_size(total)}, Used: {get_size(used)} ({100*used/total:.1f}%), Free: {get_size(free)}")

    # Network (ifconfig/ip)
    print("\033[1mInterfaces:\033[0m")
    try:
        if shutil.which("ip"):
            subprocess.run(["ip", "-brief", "addr", "show"], check=True)
        elif shutil.which("ifconfig"):
            subprocess.run(["ifconfig", "-l"], check=True)
    except:
        pass

if __name__ == "__main__":
    main()
