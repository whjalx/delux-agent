# skill:delux-oracle
## Summary
Delux Oracle — knowledge retrieval and synthesis. Queries documentation, memory, skills, and the web to produce authoritative answers with cited sources.

## When To Use
- Researching technical topics across multiple sources
- Synthesizing information from memory, docs, and skills
- Answering questions that require cross-referencing
- Generating comprehensive reports on a subject
- Validating assumptions against stored knowledge

## Steps
1. **Query**: Search memory, docs, skills, and installed tools
2. **Cross-reference**: Compare information from multiple sources
3. **Synthesize**: Combine findings into a coherent answer
4. **Cite**: Reference source locations for each claim
5. **Confidence**: Score certainty based on source reliability

## Verification
- Every claim has at least one source reference
- Conflicting information is noted, not hidden
- "I don't know" is preferred over hallucination
- Sources are specific (file paths, line numbers)

## Response Examples

### Agent invokes oracle
```json
{"action":"run_skill","skill":"delux-oracle","args":"what do we know about the deployment pipeline","timeout":30}
```

### Skill returns knowledge synthesis
```json
{
  "delux_oracle": {
    "query": "deployment pipeline",
    "sources_checked": ["memory", "docs", "skills"],
    "status": "complete",
    "confidence": 0.9,
    "findings": [
      {"source": "docs/deployment.md", "claim": "Deployment uses GitHub Actions", "confidence": "extracted"},
      {"source": "memory/memory.md", "claim": "Server is at 192.168.1.100", "confidence": "extracted"}
    ]
  }
}
```

### Prompt injection example
```
--- delux-oracle example ---
USER: "what do we know about deployment"
AGENT: {"action":"run_skill","skill":"delux-oracle","args":"deployment pipeline","timeout":30}
RESULT: {"delux_oracle": {"query": "deployment pipeline", "sources_checked": ["memory","docs"], "status": "complete", "findings": [...]}}
NEXT ACTION: {"action":"final","message":"Deployment pipeline info found in docs/deployment.md"}
```

## Caveats
- Only as good as the stored knowledge
- Web search requires MCP fetch server
- Respects memory/skill/document boundaries
