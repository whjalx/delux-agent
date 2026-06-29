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

### Agent invokes the skill
```
<action>run_skill</action>
<skill>delux-quick-search</skill>
<args>nginx configuration for reverse proxy</args>
<timeout>30</timeout>
```

### Skill returns result
```
### Web Search Results for: 'nginx configuration for reverse proxy'

1. **How to Configure NGINX as a Reverse Proxy**
   URL: https://example.com/nginx-reverse-proxy
   Snippet: A step-by-step guide to setting up NGINX as a reverse proxy server...
```

### Prompt injection example
```
--- delux-quick-search example ---
USER: "how do I install docker on fedora?"
AGENT:
<action>run_skill</action>
<skill>delux-quick-search</skill>
<args>install docker fedora</args>
<timeout>30</timeout>
RESULT: Web search results with installation steps
NEXT ACTION:
<action>shell</action>
<command>sudo dnf install -y docker</command>
<timeout>60</timeout>
```

## Caveats
- Requires `ddgr` CLI tool to be installed (`pip install ddgr` or package manager)
- Limited to 5 results to conserve context tokens
- Depends on DuckDuckGo availability; may not work in restricted networks
- Returns formatted text, not raw JSON
