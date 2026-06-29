# skill:delux-judge
## Summary
Delux Judge — impartial self-validation and critique. Reviews the agent's own actions for correctness, safety, completeness, and style compliance before finalizing.

## When To Use
- Before using "final" action — validate all work
- After complex multi-step operations
- When modifying critical system files
- Before presenting results to the user
- To catch subtle errors the agent might miss

## Usage
delux-judge <json_action>

Validates a proposed agent action for safety, correctness, and completeness.

## Steps
1. **Review**: Read back the actions taken and their results
2. **Validate**: Check correctness against the original request
3. **Safety**: Ensure no privilege escalation, destructive commands, or leaked secrets
4. **Completeness**: Verify all requirements are addressed
5. **Style**: Check output matches conventions (JSON format, no extraneous text)
6. **Verdict**: PASS, FAIL_WARNING, or FAIL_BLOCKING

## Verification
- Every action is accounted for
- No sudo/su/doas/pkexec in any command
- No IPs, keys, or secrets in output
- All user requirements are met
- JSON format is valid

## Response Examples

### Agent invokes judge before final
```
<action>run_skill</action>
<skill>delux-judge</skill>
<args>{"action":"final","message":"all done"}</args>
<timeout>15</timeout>
```

### Skill returns verdict
```
{
  "delux_judge": {
    "verdict": "PASS",
    "issues": [],
    "action_reviewed": "final",
    "recommendation": "proceed"
  }
}
```

### Judge catches a problem
```
{
  "delux_judge": {
    "verdict": "FAIL_WARNING",
    "issues": ["WARNING: Destructive pattern 'rm ' in command"],
    "action_reviewed": "shell",
    "recommendation": "review"
  }
}
```

### Prompt injection example
```
--- delux-judge example ---
USER: "validate our work before finishing"
AGENT:
<action>run_skill</action>
<skill>delux-judge</skill>
<args>{"action":"shell","command":"rm -rf /tmp/test"}</args>
<timeout>15</timeout>
RESULT: {"delux_judge": {"verdict": "FAIL_WARNING", "issues": ["WARNING: Destructive pattern 'rm ' in command"], "recommendation": "review"}}
NEXT ACTION:
<action>shell</action>
<command>ls /tmp/test</command>
<timeout>30</timeout>
```

## Caveats
- Judge cannot inspect external service side effects
- Best effort — not a formal verifier
- Use with /validate mode for extra safety
