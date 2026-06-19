# skill:delux-writer-pro
## Summary
Robust file writer. Ensures parent directories exist and handles complex multi-line content safely. Superior to echo/sed for code and config files.

## When To Use
- Creating new files with multi-line content (code, configs, scripts)
- Writing files where parent directories may not exist yet
- When you need safe file creation with verification (size check)
- Replacing echo/sed for complex content that has special characters

## Usage
delux-writer-pro <path> <content>

## Steps
1. Resolve path relative to current working directory
2. Create parent directories automatically with os.makedirs
3. Write content with UTF-8 encoding
4. Verify file was written by checking existence and size
5. Return SUCCESS with byte count or ERROR on failure

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-writer-pro","args":"src/main.py \"print('Hello World')\"","timeout":15}
```

### Skill devuelve resultado
```
SUCCESS: File 'src/main.py' written successfully (21 bytes).
```

### Prompt injection example (para few-shot learning)
```
--- delux-writer-pro example ---
USER: "create a config file at /etc/myapp/config.yml"
AGENT: {"action":"run_skill","skill":"delux-writer-pro","args":"/etc/myapp/config.yml \"server:\\n  port: 8080\\n  host: 0.0.0.0\"","timeout":15}
RESULT: SUCCESS: File '/etc/myapp/config.yml' written successfully (42 bytes).
NEXT ACTION: {"action":"final","message":"Created config file at /etc/myapp/config.yml"}
```

## Caveats
- Content is passed as a single string argument; use escaped newlines (\n) for multi-line
- Very large files may exceed argument length limits; use write_file for those cases
- Overwrites existing files without warning
