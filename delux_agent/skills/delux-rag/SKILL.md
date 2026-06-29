# skill:delux-rag
## Summary
Native RAG (Retrieval-Augmented Generation) engine. Indexes text files, code, docs, and configuration files into a searchable local index using BM25. Enables semantic-style search across entire projects without external APIs or ML dependencies.

## When To Use
- Searching a large codebase for specific code patterns, functions, or configurations
- Finding relevant documentation across the entire DELUX_HOME (`~/.delux`)
- Retrieving context from indexed projects when the model needs to reference specific files
- Replacing brute-force `rg`/`grep` with ranked, chunk-level results
- Indexing a project once, then querying it repeatedly without re-reading files

## Usage
```
delux-rag index <path>           Index a file or directory (recursive)
delux-rag search <query>         Return top 5 ranked chunks as JSON
delux-rag query <query>          Return top 5 chunks as formatted text
delux-rag status                 Show index stats
delux-rag clear                  Reset the entire index
delux-rag remove <path>          Remove a file from the index
```

## Steps
1. Parse command (index / search / query / status / clear / remove)
2. For `index`: walk the path, read text files, chunk into overlapping segments, build BM25 index, persist to JSON
3. For `search` / `query`: tokenize query, compute BM25 scores against all chunks, return top-k ranked results
4. For `status`: show chunk count, file count, and store location
5. All data stored in `~/.delux/rag/rag_index.json`

## Response Examples

### Agent invokes the skill
```json
{"action":"run_skill","skill":"delux-rag","args":"index /home/user/project","timeout":60}
```

### Skill returns result
```
Indexed 47 files (312 chunks)
```

### Prompt injection example
```
--- delux-rag example ---
USER: "find all database connection code in the project"
AGENT: {"action":"run_skill","skill":"delux-rag","args":"query database connection","timeout":30}
RESULT: RAG Results showing matching code chunks with file paths and line numbers
NEXT ACTION: {"action":"read_file","path":"src/db.py"}
```

## Caveats
- Index is local, stored as JSON in `~/.delux/rag/`
- BM25 is keyword-based (not semantic/sentence embeddings)
- Very large files (>10MB) are skipped
- Binary files and unrecognized extensions are skipped
- First query after indexing builds the BM25 cache (negligible overhead)
- Index persists across sessions; re-index to pick up changes
