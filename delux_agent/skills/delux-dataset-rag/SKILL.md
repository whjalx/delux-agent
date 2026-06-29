# skill:delux-dataset-rag
## Summary
Manages the dataset RAG — a searchable library of real agent trajectories (Hermes Agent + multiturn tool-calling) converted into few-shot examples. Small models use this to find similar solved tasks and follow the same patterns.

## When To Use
- Before starting a complex task, search for similar past agent trajectories
- When you need to see how other agents solved a similar problem
- After importing new datasets, to verify the index
- Getting few-shot examples formatted for Delux-style actions

## Usage
```
delux-dataset-rag import                    Import Hermes (kimi+glm) + Multiturn
delux-dataset-rag import --glaive           Also import Glaive function-calling
delux-dataset-rag search <query>            Search for similar tasks (formatted)
delux-dataset-rag few-shot <query>          Get Delux-style few-shot examples
delux-dataset-rag status                    Show index stats
delux-dataset-rag clear                     Reset the entire index
```

## Steps
1. Parse command (import / search / few-shot / status / clear)
2. For `import`: read parquet files, convert each entry to Markdown, index into BM25 RAG
3. For `search`: query the RAG with BM25, return ranked matching entries
4. For `few-shot`: search + format result as Delux-style example (USER/AGENT/RESULT/NEXT ACTION)
5. All data stored in `~/.delux/dataset-rag/`

## Response Examples

### Agent invokes the skill
```json
{"action":"run_skill","skill":"delux-dataset-rag","args":"few-shot write a python script to parse CSV","timeout":30}
```

### Skill returns result
```
--- Dataset RAG Few-Shot Examples ---

### Example: Write a Python script that reads a CSV file
Category: Terminal & Coding / Terminal Tasks

USER: "Write a Python script that reads a CSV..."
AGENT thinks: The user wants a Python script that reads a CSV, cleans data...
AGENT: Here's a robust Python script...
AGENT calls: {"name": "write_file", "arguments": {"path": "csv_cleaner.py", ...}}
TOOL RESULT: File written
```

### Prompt injection example
```
--- delux-dataset-rag example ---
USER: "find similar agent traces for deploying nginx"
AGENT: {"action":"run_skill","skill":"delux-dataset-rag","args":"few-shot deploy nginx configuration","timeout":30}
RESULT: Dataset examples showing real agent traces
NEXT ACTION: Continue with the task using similar patterns
```

## Caveats
- Requires `pyarrow` + `pandas` for parquet import (built-in dependencies)
- Import is one-time; subsequent runs skip already-imported entries (incremental)
- Search results are limited to top 3-5 matches to conserve context
- Dataset files are stored as Markdown in `~/.delux/dataset-rag/`
