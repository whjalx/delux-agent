import sys
import json
import os

REASONING_PREFIX = """You are Delux, a structured reasoning engine. Your task is to analyze a problem with clear step-by-step logic.

PROTOCOL OF REASONING:

1. DECOMPOSE: Break the query into atomic sub-problems
2. CONFIDENCE: Assign a confidence score (0.0-1.0) to each hypothesis
3. TRACE: Walk through each sub-problem, showing your work
4. SYNTHESIZE: Combine insights into a final answer
5. FALLBACK: If confidence < 0.7, provide fallback strategy

FORMAT:
{
  "analysis": {
    "problem_statement": "...",
    "sub_problems": [
      {"question": "...", "approach": "...", "confidence": 0.0, "fallback": "..."}
    ],
    "conclusion": "...",
    "confidence": 0.0,
    "next_action": "shell|read|write|final"
  },
  "reasoning_trace": "..."
}
"""

def reason(task: str) -> str:
    return json.dumps({
        "analysis": {
            "problem_statement": task,
            "sub_problems": [{
                "question": "Understanding the core request",
                "approach": "Parse intent, extract implicit requirements",
                "confidence": 0.9,
                "fallback": "Ask clarifying questions"
            }],
            "conclusion": f"Delux reasoning engaged for: {task[:100]}",
            "confidence": 0.85,
            "next_action": "final"
        },
        "reasoning_trace": f"Delux has analyzed the request. Proceeding with deliberate precision."
    })

if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "No task provided"
    print(reason(task))
