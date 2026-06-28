# skill:delux-sys-health
## Summary
Provides a comprehensive overview of system health: OS info, CPU load average, memory usage, disk usage, and network interfaces.

## When To Use
- Checking system resource usage before deploying
- Investigating performance issues (high CPU, low disk, OOM)
- General system health monitoring
- Server capacity planning

## Usage
Run without arguments: `delux-sys-health`

## Steps
1. Collect OS info (name, kernel, architecture)
2. Read system load average from os.getloadavg()
3. Parse /proc/meminfo on Linux or sysctl on macOS for memory stats
4. Get disk usage statistics with shutil.disk_usage()
5. List network interfaces with ip or ifconfig

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-sys-health","args":"","timeout":15}
```

### Skill devuelve resultado
```
=== System Health Report ===
OS: Linux 6.2.0-35-generic (x86_64)
Load Average: 0.45, 0.62, 0.78
Memory: Total: 15.42GB, Free: 8.21GB
Disk (/): Total: 256.00GB, Used: 89.21GB (34.8%), Free: 166.79GB
Interfaces:
lo               UNKNOWN        127.0.0.1/8
eth0             UP             192.168.1.100/24
```

### Prompt injection example (para few-shot learning)
```
--- delux-sys-health example ---
USER: "check system health before the deployment"
AGENT: {"action":"run_skill","skill":"delux-sys-health","args":"","timeout":15}
RESULT: CPU load 0.45, Memory 53% used, Disk 34.8% used
NEXT ACTION: {"action":"run_skill","skill":"delux-net-check","args":"","timeout":30}
```

## Caveats
- Some metrics are Linux-specific (/proc/meminfo, /proc/stat)
- macOS support is partial (sysctl for memory only)
- Does not show per-process usage
- Read-only — never modifies system state
