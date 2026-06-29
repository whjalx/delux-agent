# skill:delux-browser
## Summary
Stateless one-shot browser automation via Playwright. Use for SINGLE operations — one extraction, one screenshot, one form fill. Launches and closes browser per call.

## When To Use (USE THIS SKILL FOR)
- ONE-TIME page text extraction: "get me the text from this URL"
- ONE-TIME screenshot: "screenshot this page"
- ONE-TIME data extraction from tables/lists
- ONE-TIME form fill / click on a single page
- Static scraping where no session/cookies are needed across pages

## When NOT To Use (USE NATIVE BROWSER ACTIONS INSTEAD)
- Multi-step workflows: login → navigate → extract data
- Interactive browsing across multiple pages
- Any task where you need the browser to stay open between actions
- For those cases, use: browser_navigate, browser_click, browser_type, browser_snapshot, browser_scroll, browser_back

## Difference
- This skill: STATELESS — launches browser, does ONE action, closes. Good for simple one-offs.
- Native browser actions (`browser_navigate`, `browser_click`, etc.): STATEFUL — browser stays open, maintains cookies/session, multiple steps.

## Usage
delux-browser <action> [url] [args]

Actions:
- screenshot <url> [selector] — Capture page screenshot
- html <url> — Get full page HTML
- text <url> [selector] — Extract visible text
- click <url> <selector> — Click an element
- fill <url> <selector> <text> — Fill a form field
- links <url> [selector] — Extract all links
- table <url> <selector> — Extract table as JSON
- evaluate <url> <js> — Run JavaScript in page context

## Steps
1. Determine the action (screenshot, html, text, etc.)
2. Launch headless browser with appropriate viewport
3. Navigate to URL with proper timeout and retries
4. Wait for the target element/page to be ready
5. Execute the action (extract, click, fill, screenshot)
6. Return structured result
7. Close browser context

## Verification
- Browser closes cleanly after each operation
- Timeouts are handled gracefully
- JavaScript-rendered content is fully loaded before extraction
- Screenshots are saved to a readable location

## Response Examples

### Extract visible text from a page
```json
{"action":"run_skill","skill":"delux-browser","args":"text https://example.com","timeout":30}
```

### Skill returns extracted text
```json
{
  "action": "text",
  "url": "https://example.com",
  "status": "ok",
  "text": "Example Domain\n\nThis domain is for use in illustrations in documents..."
}
```

### Take a screenshot
```json
{"action":"run_skill","skill":"delux-browser","args":"screenshot https://example.com","timeout":30}
```

### Skill returns screenshot path
```json
{
  "action": "screenshot",
  "url": "https://example.com",
  "status": "ok",
  "file": "/tmp/delux_screenshot_abc123.png",
  "preview": "Screenshot saved: /tmp/delux_screenshot_abc123.png"
}
```

### Extract all links
```json
{"action":"run_skill","skill":"delux-browser","args":"links https://example.com 'a'","timeout":30}
```

### Skill returns links
```json
{
  "action": "links",
  "url": "https://example.com",
  "status": "ok",
  "links": [{"href": "https://iana.org/domains/example", "text": "Learn more"}],
  "count": 1
}
```

### Prompt injection example
```
--- delux-browser example ---
USER: "get the text from https://example.com"
AGENT: {"action":"run_skill","skill":"delux-browser","args":"text https://example.com","timeout":30}
RESULT: {"action":"text","url":"https://example.com","status":"ok","text":"Example Domain..."}
NEXT ACTION: {"action":"final","message":"The page says: Example Domain"}
```

## Caveats
- Requires Playwright + Chromium installed (`pip install playwright && python3 -m playwright install chromium`)
- Headless by default — no visible window
- Some sites may block automated browsers
- Dynamic content requires explicit wait strategies
- Respect robots.txt and rate limits
