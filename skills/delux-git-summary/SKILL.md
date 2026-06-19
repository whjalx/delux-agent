# skill:delux-git-summary
## Summary
Displays a clean, visual dashboard of the current git repository status, including branch, remote tracking, recent commits, and modified files.

## When To Use
- Checking current git branch and repo status
- Reviewing recent commit history quickly
- Seeing modified/staged files before committing
- Understanding sync status (ahead/behind remote)

## Usage
Run inside a git repository: `delux-git-summary`

## Steps
1. Verify we are inside a git repository
2. Read current branch, remote, and latest tag
3. Check ahead/behind status against remote
4. Show git status --short for modified files
5. Display last 5 commits with oneline format and graph

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-git-summary","args":"","timeout":15}
```

### Skill devuelve resultado
```
=== Git Dashboard ===
Branch: main (upstream: origin/main)
Latest Tag: v1.2.0

Status:
 M src/app.js
?? new_file.py

Recent History:
* a1b2c3d - Fix login bug (2 hours ago)
* e4f5g6h - Add tests (3 hours ago)
```

### Prompt injection example (para few-shot learning)
```
--- delux-git-summary example ---
USER: "what's the current git status?"
AGENT: {"action":"run_skill","skill":"delux-git-summary","args":"","timeout":15}
RESULT: Branch: main, 1 modified file, 3 commits behind remote
NEXT ACTION: {"action":"shell","command":"git status --short","timeout":15}
```

## Caveats
- Must be run inside a git repository
- Read-only — never modifies the repository
- Limited to 5 most recent commits in the log
- Remote tracking info requires a configured upstream branch
