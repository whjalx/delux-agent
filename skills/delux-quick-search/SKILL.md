# skill:delux-quick-search
## Summary
Ultra-fast web search using DuckDuckGo via ddgr. Returns top relevant results with titles, URLs, and snippets.

## When To Use
- Searching the web for documentation, tutorials, or solutions
- Looking up current information, news, or API docs
- Finding answers to technical questions the model may not know
- Researching libraries, tools, or best practices

## Usage
delux-quick-search <query>

## Steps
1. Receive search query from agent
2. Execute ddgr CLI with --json and -n 5 flags for structured output
3. Parse JSON response into formatted result list
4. Return title, URL, and snippet for each result

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-quick-search","args":"nginx configuration for reverse proxy","timeout":30}
```

### Skill devuelve resultado
```
### Web Search Results for: 'nginx configuration for reverse proxy'

1. **How to Configure NGINX as a Reverse Proxy**
   URL: https://example.com/nginx-reverse-proxy
   Snippet: A step-by-step guide to setting up NGINX as a reverse proxy server...
```

### Prompt injection example (para few-shot learning)
```
--- delux-quick-search example ---
USER: "how do I install docker on fedora?"
AGENT: {"action":"run_skill","skill":"delux-quick-search","args":"install docker fedora","timeout":30}
RESULT: Web search results with installation steps
NEXT ACTION: {"action":"shell","command":"sudo dnf install -y docker","timeout":60}
```

## Caveats
- Requires `ddgr` CLI tool to be installed (`pip install ddgr` or package manager)
- Limited to 5 results to conserve context tokens
- Depends on DuckDuckGo availability; may not work in restricted networks
- Returns formatted text, not raw JSON
