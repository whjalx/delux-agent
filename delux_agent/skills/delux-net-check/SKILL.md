# skill:delux-net-check
## Summary
Performs quick network diagnostics, checking local connectivity, DNS resolution, and external ping to major providers (Google, Cloudflare, GitHub). Also attempts to discover the public IP.

## When To Use
- Diagnosing network connectivity issues
- Checking DNS resolution is working
- Verifying internet access from a server
- Quick network health check before other operations

## Usage
Run without arguments: `delux-net-check`

## Steps
1. Ping localhost to verify basic network stack
2. Resolve google.com via DNS to check DNS is working
3. Ping external targets (8.8.8.8, 1.1.1.1, github.com) with latency measurement
4. Attempt public IP discovery via ifconfig.me using curl
5. Report pass/fail with timing for each check

## Response Examples

### Agent invokes the skill
```
<action>run_skill</action>
<skill>delux-net-check</skill>
<args></args>
<timeout>30</timeout>
```

### Skill returns result
```
=== Network Diagnostics ===
Localhost (127.0.0.1): OK
DNS Resolution (google.com): OK
External Connectivity:
  Google (8.8.8.8)        : OK (12.3ms)
  Cloudflare (1.1.1.1)    : OK (8.1ms)
  Github (github.com)     : OK (45.2ms)
Public IP: 203.0.113.42
```

### Prompt injection example
```
--- delux-net-check example ---
USER: "check if the server has internet access"
AGENT:
<action>run_skill</action>
<skill>delux-net-check</skill>
<args></args>
<timeout>30</timeout>
RESULT: All checks passed
NEXT ACTION:
<action>final</action>
<message>Server has full network connectivity</message>
```

## Caveats
- Requires ping command and network access
- Public IP detection requires curl
- Firewalls may block ICMP (ping) even if HTTP works
- Read-only — never modifies system state
