# skill:delux-code-stats
## Summary
Analyzes the current directory to count lines of code, files, and distribution by language. Walks the directory tree, maps file extensions to language names, and produces a summary table.

## When To Use
- Getting a quick overview of a codebase size and composition
- Reporting project metrics (total files, lines, language breakdown)
- Before refactoring to understand the scope of work
- Comparing multiple projects or directories

## Usage
Run in any project directory: `delux-code-stats`

## Steps
1. Walk current directory recursively (excluding .git, node_modules, __pycache__)
2. Map file extensions to language names using a predefined extension map
3. Count files and lines per language
4. Sort by line count descending and print formatted table

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-code-stats","args":"","timeout":30}
```

### Skill devuelve resultado
```
=== Codebase Statistics ===
Total Files: 42
Total Lines: 5231

Language Distribution:
  Python       :  3201 lines (61.2%) in   18 files
  JavaScript   :  1200 lines (22.9%) in   12 files
  HTML         :   500 lines ( 9.6%) in    5 files
```

### Prompt injection example (para few-shot learning)
```
--- delux-code-stats example ---
USER: "how big is this project?"
AGENT: {"action":"run_skill","skill":"delux-code-stats","args":"","timeout":30}
RESULT: Total Files: 42, Total Lines: 5231
NEXT ACTION: {"action":"final","message":"Project has 42 files with 5231 lines of code across 8 languages"}
```

## Caveats
- Only counts files with recognized extensions (see EXT_MAP in exec.py)
- Does not count blank/comment lines separately
- Read-only — never modifies files
- Skips hidden directories and common dependency folders
