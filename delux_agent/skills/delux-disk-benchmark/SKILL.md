# skill:delux-disk-benchmark
## Summary
Professional-grade disk performance benchmark written in C. Measures sequential write and read speeds using direct system calls for accurate raw performance metrics.

## When To Use
- Testing disk performance (write/read throughput)
- Comparing storage devices or filesystems
- Investigating slow I/O performance
- Benchmarking before and after hardware changes

## Usage
delux-disk-benchmark [size_in_mb]

Default size: 100MB. Specify a custom size as the first argument.

## Steps
1. Allocate a 1MB buffer filled with dummy data
2. Open a temporary file and write in 1MB sequential blocks
3. Call fsync to ensure data is on disk
4. Read back the same file in 1MB sequential blocks
5. Calculate and display throughput in MB/s for both write and read
6. Clean up the temporary file

## Response Examples

### Agent invokes the skill
```json
{"action":"run_skill","skill":"delux-disk-benchmark","args":"200","timeout":30}
```

### Skill returns result
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  🚀 DELUX DISK BENCHMARK (C Engine)                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Target size: 200 MB
Buffer size: 1 MB

[OK] Sequential Write: 450.32 MB/s (200 MB in 0.444s)
[OK] Sequential Read:  1200.85 MB/s (200 MB in 0.167s)

Benchmark Finished.
```

### Prompt injection example
```
--- delux-disk-benchmark example ---
USER: "how fast is the disk on this server?"
AGENT: {"action":"run_skill","skill":"delux-disk-benchmark","args":"100","timeout":30}
RESULT: Sequential Write: 450 MB/s, Sequential Read: 1200 MB/s
NEXT ACTION: {"action":"final","message":"Disk benchmark: 450 MB/s write, 1200 MB/s read"}
```

## Caveats
- Writes a temporary file to the current directory (cleaned up after)
- Requires a C compiler (gcc) — auto-compiled on first run
- Tests sequential performance only, not random I/O or IOPS
- Results vary based on filesystem cache, disk type (SSD/HDD), and system load
