# skill:delux-obsidian-brain
## Summary
Knowledge Base manager for deep learning and research. Stores technical notes, code examples, guides, and documentation as Markdown files compatible with Obsidian's Knowledge Graph. NOT for personal/general memory.

## When To Use
- Saving technical solutions, code patterns, and architectural decisions
- Storing research findings with cross-links between related topics
- Building a persistent knowledge base that survives session resets
- Retrieving previously saved technical knowledge

## Usage
- `add <topic> "<content>" [-l <link1> <link2>]`: Create or append to a note
- `read <topic>`: Read a note's full content
- `list`: List all saved notes

## Steps
1. Receive command (add/read/list) with arguments
2. For add: resolve topic name, create or append to Markdown file with timestamp
3. For read: resolve topic name and display full content
4. For list: show all .md files in the Obsidian vault directory
5. Support cross-links with [[WikiLink]] syntax for graph navigation

## Response Examples

### Agent invokes the skill
```
<action>run_skill</action>
<skill>delux-obsidian-brain</skill>
<args>add Kubernetes "Learned: kubectl port-forward enables local access to pods" -l Networking Debugging</args>
<timeout>15</timeout>
```

### Skill returns result
```
✅ Created new note: [[Kubernetes]]
```

### Prompt injection example
```
--- delux-obsidian-brain example ---
USER: "save that nginx config fix for later"
AGENT:
<action>read_file</action>
<path>/etc/nginx/sites-enabled/default</path>
RESULT: (file content)
AGENT:
<action>run_skill</action>
<skill>delux-obsidian-brain</skill>
<args>add Nginx "Fixed reverse proxy by adding proxy_pass http://localhost:3000" -l WebServer Proxy</args>
<timeout>15</timeout>
RESULT: ✅ Added content to note: [[Nginx]]
NEXT ACTION:
<action>remember</action>
<note>Saved nginx reverse proxy fix to knowledge base</note>
```

## Caveats
- Stores notes in `~/.delux/obsi/` (or `$OBSIDIAN_VAULT`)
- NOT for personal memory — use `remember` action for that
- Notes persist across sessions and can be opened in Obsidian
- Topic names are normalized: case-insensitive matching
