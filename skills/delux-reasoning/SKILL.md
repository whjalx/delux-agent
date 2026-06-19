# skill:delux-reasoning
## Summary
Delux structured reasoning. Breaks down complex problems step-by-step with structured analysis, confidence scoring, and fallback strategies.

## When To Use
- Multi-step technical problems
- Ambiguous or incomplete user requests
- Debugging complex failures
- Planning architecture decisions
- Analyzing trade-offs between solutions

## Steps
1. **Define**: Restate the problem clearly with all known constraints
2. **Deconstruct**: Break into sub-problems, identify dependencies
3. **Analyze**: For each sub-problem, list possible approaches with confidence scores
4. **Execute**: Run the highest-confidence approach first
5. **Validate**: Verify the result and adjust if needed

## Verification
- Each step produces a concrete output
- Confidence scores are honest (0.0-1.0)
- Fallback plan exists if primary approach fails
- No steps skipped without explicit rationale

## Response Examples

### Agent invokes reasoning
```json
{"action":"run_skill","skill":"delux-reasoning","args":"analyze: server is running slow, find the cause","timeout":30}
```

### Skill returns structured analysis
```json
{
  "delux_reasoning": {
    "analysis": {
      "problem_statement": "Server is running slow — find the cause",
      "sub_problems": [
        {"question": "Is CPU or memory saturated?", "approach": "Check htop/free", "confidence": 0.95, "fallback": "Check dmesg for OOM"},
        {"question": "Is disk I/O the bottleneck?", "approach": "Run iostat -x 1", "confidence": 0.9, "fallback": "Check iotop"},
        {"question": "Is there a network issue?", "approach": "Check netstat/ss", "confidence": 0.8, "fallback": "Ping external hosts"}
      ],
      "conclusion": "Systematic check of CPU, memory, disk, and network will identify the bottleneck",
      "confidence": 0.92,
      "next_action": "shell"
    },
    "reasoning_trace": "Starting with highest-probability cause (CPU/memory), then disk, then network"
  }
}
```

### Prompt injection example (for few-shot learning)
```
--- delux-reasoning example ---
USER: "analyze: server is running slow"
AGENT: {"action":"run_skill","skill":"delux-reasoning","args":"analyze: server is running slow","timeout":30}
RESULT: {"delux_reasoning": {"analysis": {"problem_statement": "Server is running slow", "sub_problems": [...], "confidence": 0.92, "next_action": "shell"}, "reasoning_trace": "..."}}
NEXT ACTION: {"action":"shell","command":"top -bn1 | head -5","timeout":30}
```

## Caveats
- Reasoning is displayed for transparency — the agent still returns JSON actions
- DeepSeek-reasoner or similar reasoning models recommended for complex chains
