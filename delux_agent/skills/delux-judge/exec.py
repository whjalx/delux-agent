import sys
import json
import re

DESTRUCTIVE_PATTERNS = ["rm ", "rm -", "> ", ">> ", "mv ", "chmod ", "chown ",
                         "truncate", "shred", "dd if=", "mkfs", "wipe"]
BLOCKED_COMMANDS = {"sudo", "su", "doas", "pkexec", "passwd", "visudo"}
SECRET_PATTERNS = [
    r'api[_-]?key\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}',
    r'token\s*[:=]\s*["\']?[a-zA-Z0-9_\-\.]{16,}',
    r'secret\s*[:=]\s*["\']?.{16,}',
    r'password\s*[:=]\s*["\']?.{8,}',
    r'sk-[a-zA-Z0-9]{20,}',
]


def judge_action(action: dict, result: str, original_request: str) -> str:
    issues = []
    kind = action.get("action", "")

    # Check for destructive commands
    if kind == "shell":
        cmd = action.get("command", "")
        for pat in DESTRUCTIVE_PATTERNS:
            if pat in cmd:
                issues.append(f"WARNING: Destructive pattern '{pat}' in command")
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd.split():
                issues.append(f"BLOCKING: Privilege escalation command '{blocked}'")

    # Check for secrets in results
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, result, re.IGNORECASE):
            issues.append("WARNING: Potential secret/key leaked in output")

    # Check for errors
    if result.startswith("ERROR:"):
        issues.append(f"WARNING: Action returned error: {result[:100]}")

    if issues:
        verdict = "FAIL_BLOCKING" if any("BLOCKING" in i for i in issues) else "FAIL_WARNING"
    else:
        verdict = "PASS"

    return json.dumps({
        "delux_judge": {
            "verdict": verdict,
            "issues": issues,
            "action_reviewed": kind,
            "recommendation": "proceed" if verdict == "PASS" else "review",
        }
    })


if __name__ == "__main__":
    action_json = sys.argv[1] if len(sys.argv) > 1 else "{}"
    result = sys.argv[2] if len(sys.argv) > 2 else ""
    request = sys.argv[3] if len(sys.argv) > 3 else ""
    try:
        action = json.loads(action_json)
    except json.JSONDecodeError:
        action = {}
    print(judge_action(action, result, request))
