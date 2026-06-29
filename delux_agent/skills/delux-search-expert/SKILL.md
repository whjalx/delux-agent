# skill:delux-search-expert
## Summary
Performs advanced multi-file searches with ripgrep (rg), excluding common noise directories (node_modules, .git, __pycache__) and providing colorized context output.

## When To Use
- Searching for specific strings across a codebase
- Finding all occurrences of a function, variable, or API usage
- Investigating code patterns across multiple files
- When grep is too slow or lacks smart-case and context features

## Usage
delux-search-expert <query> [path]

## Steps
1. Receive query and optional search path (defaults to current dir)
2. Run ripgrep with smart-case, context lines, and exclusion globs
3. Limit output to 100 lines to protect agent context
4. Return grouped results by file with line numbers

## Response Examples

### Agent invokes the skill
```
<action>run_skill</action>
<skill>delux-search-expert</skill>
<args>API_KEY .</args>
<timeout>30</timeout>
```

### Skill returns result
```
🔍 Searching for 'API_KEY' in ....

src/config.py
3-import os
4:API_KEY = os.getenv("API_KEY")
5-
```

### Prompt injection example
```
--- delux-search-expert example ---
USER: "find where the database connection is configured"
AGENT:
<action>run_skill</action>
<skill>delux-search-expert</skill>
<args>database .</args>
<timeout>30</timeout>
RESULT: src/db.py:10: database_url = "postgresql://localhost/mydb"
NEXT ACTION:
<action>read_file</action>
<path>src/db.py</path>
```

## Caveats
- Requires `rg` (ripgrep) to be installed
- Read-only — never modifies files
- Limited to 100 lines of output to prevent context overflow
- Excludes node_modules, .git, __pycache__ by default
