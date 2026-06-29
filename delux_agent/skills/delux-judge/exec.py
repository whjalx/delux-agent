#!/usr/bin/env python3
"""Action validator & security scanner — production-grade CLI with JSON output."""

import json
import re
import sys
import traceback

MAX_RESULT_SIZE = 100000
MAX_COMMAND_SIZE = 10000
MAX_REQUEST_SIZE = 100000

DESTRUCTIVE_PATTERNS: list[tuple[str, str, str]] = [
    ("rm ", "command removes files/directories", "FAIL_WARNING"),
    ("rm -rf", "command recursively force-removes files", "FAIL_BLOCKING"),
    ("rm -r", "command recursively removes directories", "FAIL_WARNING"),
    ("> ", "command overwrites a file via redirect", "FAIL_WARNING"),
    (">> ", "command appends/creates file via redirect", "FAIL_WARNING"),
    ("dd if=", "low-level disk copy/destroy operation", "FAIL_BLOCKING"),
    ("dd bs=", "low-level disk operation", "FAIL_BLOCKING"),
    ("mkfs.", "filesystem creation (destroys existing data)", "FAIL_BLOCKING"),
    ("mkfs ", "filesystem creation (destroys existing data)", "FAIL_BLOCKING"),
    ("shred ", "secure file deletion", "FAIL_BLOCKING"),
    ("truncate ", "file truncation", "FAIL_WARNING"),
    ("wipe ", "disk/data wiping", "FAIL_BLOCKING"),
    ("fdisk ", "disk partitioning tool", "FAIL_BLOCKING"),
    ("parted ", "disk partitioning tool", "FAIL_BLOCKING"),
    ("mkswap ", "swap creation (can destroy existing partitions)", "FAIL_BLOCKING"),
    ("pvcreate ", "LVM physical volume creation", "FAIL_BLOCKING"),
    ("vgremove ", "LVM volume group removal", "FAIL_BLOCKING"),
    ("lvremove ", "LVM logical volume removal", "FAIL_BLOCKING"),
    ("cryptsetup ", "disk encryption setup (destructive if misused)", "FAIL_BLOCKING"),
    ("format ", "disk formatting command", "FAIL_BLOCKING"),
    ("chmod 777", "world-writable permission (security risk)", "FAIL_WARNING"),
    ("chmod -R 777", "recursive world-writable permission", "FAIL_BLOCKING"),
    ("chmod 666", "world-writable file permission", "FAIL_WARNING"),
    ("chmod o+w ", "adds world-write permission", "FAIL_WARNING"),
    ("chmod o=rwx", "sets world-read/write/execute", "FAIL_WARNING"),
    ("chown root", "changing ownership to root", "FAIL_BLOCKING"),
    ("chown -R root", "recursive ownership change to root", "FAIL_BLOCKING"),
    ("chown :root", "changing group to root", "FAIL_WARNING"),
    ("chown 0:0", "changing ownership to uid/gid 0", "FAIL_BLOCKING"),
    ("chattr +i", "making file immutable (can break systems)", "FAIL_WARNING"),
    (":(){ :|:& };:", "fork bomb pattern", "FAIL_BLOCKING"),
    ("/dev/null of=/dev/sd", "writing directly to block device", "FAIL_BLOCKING"),
    ("/dev/sda", "referencing raw block device", "FAIL_BLOCKING"),
    ("/dev/nvme0", "referencing raw NVMe device", "FAIL_BLOCKING"),
    ("mount --bind", "bind mount (potential security bypass)", "FAIL_WARNING"),
    ("mount -o remount", "remount filesystem", "FAIL_WARNING"),
    ("umount -l", "lazy unmount (risk of data loss)", "FAIL_WARNING"),
    ("systemctl disable", "disabling system services", "FAIL_WARNING"),
    ("systemctl mask", "masking system services", "FAIL_BLOCKING"),
    ("iptables -F", "flushing firewall rules", "FAIL_BLOCKING"),
    ("iptables -P", "changing firewall default policy", "FAIL_BLOCKING"),
    ("nft flush ruleset", "flushing nftables rules", "FAIL_BLOCKING"),
    ("passwd -d", "deleting user password (no-password login)", "FAIL_BLOCKING"),
    ("userdel ", "deleting user account", "FAIL_BLOCKING"),
    ("groupdel ", "deleting group", "FAIL_WARNING"),
    ("mv /etc/", "moving /etc/ directory content", "FAIL_BLOCKING"),
    ("mv /boot/", "moving /boot/ directory content", "FAIL_BLOCKING"),
]

BLOCKED_COMMANDS: set[str] = {
    "sudo", "su", "doas", "pkexec", "passwd", "visudo",
    "runuser", "chroot", "newgrp", "sg", "sudoedit",
}

PRIVILEGE_PATTERNS: list[str] = [
    r"\bsudo\s",
    r"\bsu\s+-",
    r"\bsu\s+root\b",
    r"\bdoas\s",
    r"\bpkexec\s",
    r"\brunuser\s",
    r"\bchroot\s",
    r"\bnewgrp\s",
    r"\bsudoedit\s",
    r"\bvisudo\b",
    r"\bpasswd\s",
    r"\bsetuid\b",
    r"\bsetcap\s",
    r"\bcapsh\s",
    r"\bgetcap\s",
]

SUSPICIOUS_PATTERNS: list[tuple[str, str, str]] = [
    (r"eval\s+.*\$", "eval with variable expansion (command injection risk)", "FAIL_WARNING"),
    (r"exec\s*\(.*\)", "exec function call in code", "FAIL_WARNING"),
    (r"os\.system\s*\(", "os.system call", "FAIL_WARNING"),
    (r"subprocess\.(call|run|Popen)\s*\(", "subprocess execution", "FAIL_WARNING"),
    (r"__import__\s*\(.*os", "dynamic import of os module", "FAIL_WARNING"),
    (r"__import__\s*\(.*subprocess", "dynamic import of subprocess module", "FAIL_WARNING"),
    (r"__import__\s*\(.*pty", "dynamic import of pty module", "FAIL_WARNING"),
    (r"__import__\s*\(.*ctypes", "dynamic import of ctypes module", "FAIL_WARNING"),
    (r"pickle\.(loads|load)\s*\(", "pickle deserialization (RCE risk)", "FAIL_BLOCKING"),
    (r"marshal\.loads\s*\(", "marshal deserialization", "FAIL_WARNING"),
    (r"yaml\.load\s*\(", "unsafe yaml loading", "FAIL_WARNING"),
    (r"base64\s+.*-d\b", "base64 decode command (potential obfuscation)", "FAIL_WARNING"),
    (r"base64\s+--decode\b", "base64 decode command (potential obfuscation)", "FAIL_WARNING"),
    (r"openssl\s+enc\s+", "openssl encryption (potential data exfiltration)", "FAIL_WARNING"),
    (r"curl\s+.*\|\s*(ba)?sh", "curl piped to shell (RCE risk)", "FAIL_BLOCKING"),
    (r"wget\s+.*\|\s*(ba)?sh", "wget piped to shell (RCE risk)", "FAIL_BLOCKING"),
    (r"curl\s+.*-o\s+", "curl downloading files", "FAIL_WARNING"),
    (r"wget\s+.*-O\s+", "wget downloading files", "FAIL_WARNING"),
    (r"\bnc\s+-[el]", "netcat listener / backdoor pattern", "FAIL_BLOCKING"),
    (r"\bncat\s+-[el]", "ncat listener / backdoor pattern", "FAIL_BLOCKING"),
    (r"\bsocat\s+.*exec", "socat with exec (potential backdoor)", "FAIL_BLOCKING"),
    (r"/dev/tcp/", "bash TCP device (reverse shell)", "FAIL_BLOCKING"),
    (r"python\s+-c\s+.*socket", "python socket (potential reverse shell)", "FAIL_BLOCKING"),
    (r"bash\s+-i\s+>&", "bash interactive reverse shell", "FAIL_BLOCKING"),
    (r"bash\s+-i\s+>/dev", "bash reverse shell", "FAIL_BLOCKING"),
    (r"\.ssh/known_hosts", "modifying SSH known hosts", "FAIL_WARNING"),
    (r"\.ssh/authorized_keys", "modifying SSH authorized keys", "FAIL_BLOCKING"),
    (r">>\s*~/.ssh/authorized_keys", "appending to authorized_keys", "FAIL_BLOCKING"),
    (r"python\s+-m\s+http\.server", "starting HTTP server", "FAIL_WARNING"),
    (r"python\s+-m\s+SimpleHTTPServer", "starting HTTP server", "FAIL_WARNING"),
    (r"ngrok\s", "ngrok tunnel (potential data exfiltration)", "FAIL_WARNING"),
]

SECRET_PATTERNS: list[tuple[str, str]] = [
    (r'api[_-]?key\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}', "API key assigned in plaintext"),
    (r'token\s*[:=]\s*["\']?[a-zA-Z0-9_\-\.]{16,}', "Token assigned in plaintext"),
    (r'secret\s*[:=]\s*["\']?.{16,}', "Secret value in plaintext"),
    (r'password\s*[:=]\s*["\']?.{8,}', "Password in plaintext"),
    (r'passwd\s*[:=]\s*["\']?.{8,}', "Password in plaintext"),
    (r'pwd\s*[:=]\s*["\']?.{8,}', "Password in plaintext"),
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key"),
    (r'sk-proj-[a-zA-Z0-9]{20,}', "OpenAI project API key"),
    (r'sk-ant-[a-zA-Z0-9]{20,}', "Anthropic API key"),
    (r'sk-admin-[a-zA-Z0-9]{20,}', "OpenAI admin key"),
    (r'xai-[a-zA-Z0-9]{20,}', "xAI API key"),
    (r'AIza[0-9A-Za-z\-_]{35}', "Google API key"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub personal access token (classic)"),
    (r'gho_[a-zA-Z0-9]{36}', "GitHub OAuth access token"),
    (r'ghu_[a-zA-Z0-9]{36}', "GitHub user-to-server token"),
    (r'ghs_[a-zA-Z0-9]{36}', "GitHub server-to-server token"),
    (r'github_pat_[a-zA-Z0-9_]{22,}', "GitHub fine-grained token"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key ID"),
    (r'aws_access_key_id\s*[:=]\s*["\']?[A-Z0-9]{16,}', "AWS access key"),
    (r'aws_secret_access_key\s*[:=]\s*["\']?\S{16,}', "AWS secret access key"),
    (r'BEGIN\s+(RSA|DSA|EC|OPENSSH|PGP)\s+PRIVATE\s+KEY', "Private key block"),
    (r'-----BEGIN\s+PRIVATE\s+KEY-----', "Private key block"),
    (r'-----BEGIN\s+ENCRYPTED\s+PRIVATE\s+KEY-----', "Encrypted private key block"),
    (r'\.env\s*["\']?[A-Z0-9_]+=["\'][^\'"]+["\']', "Environment variable with value in .env format"),
    (r'DATABASE_URL\s*[:=]\s*.{10,}', "Database connection string"),
    (r'mongodb(\+srv)?://[^:\s]+:[^@\s]+@', "MongoDB connection string with credentials"),
    (r'postgres(ql)?://[^:\s]+:[^@\s]+@', "PostgreSQL connection string with credentials"),
    (r'mysql://[^:\s]+:[^@\s]+@', "MySQL connection string with credentials"),
    (r'redis://[^:\s]+:[^@\s]+@', "Redis connection string with credentials"),
    (r'Authorization\s*[:=]\s*["\']?Bearer\s+\S{20,}', "Authorization Bearer token"),
    (r'Authorization\s*[:=]\s*["\']?Basic\s+\S{10,}', "Authorization Basic token"),
    (r'eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}', "JWT token"),
    (r't\.[a-f0-9]{24,}', "Telegram bot token"),
    (r'npm_[a-zA-Z0-9]{36}', "npm access token"),
    (r'pypi-AgEIc[A-Za-z0-9\-_]{30,}', "PyPI API token"),
    (r'hf_[a-zA-Z0-9]{34}', "HuggingFace API token"),
    (r'xox[bpras]-[0-9a-zA-Z\-]{10,}', "Slack bot/user token"),
    (r'sk-[a-zA-Z0-9]{48,}', "GitHub Copilot token"),
    (r'skey-\S{10,}', "OpenRouter secret key"),
]

ERROR_PATTERNS: list[tuple[str, str]] = [
    ("ERROR:", "Action returned error"),
    ("Traceback (most recent call last)", "Python traceback in output"),
    ("Permission denied", "Permission denied error"),
    ("command not found", "Command not found error"),
    ("No such file or directory", "Missing file/directory"),
    ("Connection refused", "Connection refused"),
    ("cannot access", "Cannot access resource"),
    ("FATAL:", "Fatal error"),
    ("panic:", "Go panic in output"),
    ("Segmentation fault", "Segfault occurred"),
    ("out of memory", "Out of memory error"),
    ("disk quota exceeded", "Disk quota exceeded"),
    ("500 Internal Server Error", "HTTP 500 error"),
    ("502 Bad Gateway", "HTTP 502 error"),
    ("503 Service Unavailable", "HTTP 503 error"),
    ("504 Gateway Timeout", "HTTP 504 error"),
]


def _validate_input(action_json_raw: str, result: str, request: str) -> tuple[dict, str, str]:
    """Validate and sanitize all inputs. Returns (action_dict, result, request)."""
    if not isinstance(action_json_raw, str):
        raise ValueError("action_json must be a string")
    if not isinstance(result, str):
        raise ValueError("result must be a string")
    if not isinstance(request, str):
        raise ValueError("request must be a string")

    if len(result) > MAX_RESULT_SIZE:
        result = result[:MAX_RESULT_SIZE]

    if len(request) > MAX_REQUEST_SIZE:
        request = request[:MAX_REQUEST_SIZE]

    action_json_raw = action_json_raw.strip()
    if not action_json_raw:
        action_dict = {}
    else:
        try:
            action_dict = json.loads(action_json_raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in action: {str(e)[:200]}")
        if not isinstance(action_dict, dict):
            raise ValueError("action must be a JSON object")

    return action_dict, result, request


def _check_destructive_commands(action: dict) -> list[dict]:
    """Check command/action for destructive patterns."""
    issues: list[dict] = []
    kind = action.get("action", "")
    cmd = action.get("command", "")

    if kind == "shell" and cmd:
        if not isinstance(cmd, str):
            return issues
        if len(cmd) > MAX_COMMAND_SIZE:
            issues.append({
                "level": "FAIL_WARNING",
                "message": f"Command exceeds maximum length ({MAX_COMMAND_SIZE} chars). Truncated.",
            })
            cmd = cmd[:MAX_COMMAND_SIZE]

        for pattern, description, level in DESTRUCTIVE_PATTERNS:
            if pattern in cmd:
                issues.append({
                    "level": level,
                    "message": f"{description}. Matched pattern: '{pattern}' in command.",
                    "command_snippet": cmd[:200],
                })

        for blocked in sorted(BLOCKED_COMMANDS):
            tokens = cmd.split()
            if blocked in tokens:
                issues.append({
                    "level": "FAIL_BLOCKING",
                    "message": f"Privilege escalation binary '{blocked}' detected in command.",
                    "command_snippet": cmd[:200],
                })

        for pattern in PRIVILEGE_PATTERNS:
            if re.search(pattern, cmd):
                issues.append({
                    "level": "FAIL_BLOCKING",
                    "message": f"Privilege escalation pattern detected: '{pattern}'",
                    "command_snippet": cmd[:200],
                })

        for pattern, description, level in SUSPICIOUS_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                issues.append({
                    "level": level,
                    "message": f"{description}.",
                    "command_snippet": cmd[:200],
                })

    # Also check file paths that appear dangerous
    path = action.get("path", "")
    if isinstance(path, str) and path:
        for dangerous_path in ("/etc/passwd", "/etc/shadow", "/etc/sudoers", "/root/", "~/.ssh/"):
            if dangerous_path in path:
                issues.append({
                    "level": "FAIL_BLOCKING",
                    "message": f"Accessing sensitive file path: {dangerous_path}",
                })

    # Check write_file / edit_file content for suspicious code
    content = action.get("content", "") or action.get("old_str", "") or action.get("new_str", "")
    if isinstance(content, str) and content:
        for pattern, description, level in SUSPICIOUS_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                is_write = action.get("action", "") in ("write_file", "edit_file", "append_file")
                prefix = "File content contains" if is_write else "Content contains"
                issues.append({
                    "level": level,
                    "message": f"{prefix} {description.lower()}.",
                })

    return issues


def _check_secret_leaks(result: str) -> list[dict]:
    """Check result/output for secret leaks."""
    issues: list[dict] = []
    for pattern, description in SECRET_PATTERNS:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            matched_text = match.group(0)
            sanitized = matched_text[:4] + "***" + (matched_text[-4:] if len(matched_text) > 8 else "")
            issues.append({
                "level": "FAIL_WARNING",
                "message": f"Potential secret leak: {description}. Matched: '{sanitized}'",
            })
    return issues


def _check_errors(result: str) -> list[dict]:
    """Check result for error patterns."""
    issues: list[dict] = []
    for pattern, description in ERROR_PATTERNS:
        if re.search(pattern, result[:5000], re.IGNORECASE):
            issues.append({
                "level": "FAIL_WARNING",
                "message": f"{description}. Pattern: '{pattern}'",
            })
    return issues


def _validate_action_structure(action: dict) -> list[dict]:
    """Validate that the action dict has required structure."""
    issues: list[dict] = []
    if not isinstance(action, dict):
        return [{"level": "FAIL_WARNING", "message": "Action is not a valid JSON object"}]
    if "action" not in action:
        issues.append({
            "level": "FAIL_WARNING",
            "message": "Missing 'action' field in action dictionary",
        })
    return issues


def judge_action(action_json: str, result: str, request: str = "") -> str:
    """Judge an action for safety and correctness. Returns JSON string."""
    try:
        action, result, request = _validate_input(action_json, result, request)
    except ValueError as e:
        return json.dumps({
            "status": "error",
            "error": str(e),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"Input validation error: {str(e)[:500]}",
        }, ensure_ascii=False)

    try:
        all_issues: list[dict] = []

        all_issues.extend(_validate_action_structure(action))
        all_issues.extend(_check_destructive_commands(action))
        all_issues.extend(_check_errors(result))
        all_issues.extend(_check_secret_leaks(result))

        if not all_issues:
            verdict = "PASS"
            recommendation = "Proceed. No security issues detected."
        elif any(i.get("level") == "FAIL_BLOCKING" for i in all_issues):
            verdict = "FAIL_BLOCKING"
            recommendation = (
                "BLOCK this action immediately. Destructive or privilege-escalation "
                "patterns detected that could compromise the system."
            )
        else:
            verdict = "FAIL_WARNING"
            recommendation = (
                "Review required. Warning-level issues detected. "
                "Consider using safe alternatives or manual approval."
            )

        return json.dumps({
            "status": "ok",
            "data": {
                "verdict": verdict,
                "issues": all_issues,
                "issue_count": len(all_issues),
                "action_reviewed": action.get("action", "unknown"),
                "recommendation": recommendation,
            },
        }, indent=2, ensure_ascii=False)

    except Exception:
        return json.dumps({
            "status": "error",
            "error": f"Judgment error: {traceback.format_exc()[:1000]}",
        }, ensure_ascii=False)


def _print_json(status: str, data: dict | None = None, error: str | None = None) -> None:
    """Print a standardized JSON response."""
    if status == "error":
        print(json.dumps({"status": "error", "error": error or "Unknown error"}, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "data": data or {}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        action_json = sys.argv[1] if len(sys.argv) > 1 else ""
        result = sys.argv[2] if len(sys.argv) > 2 else ""
        request = sys.argv[3] if len(sys.argv) > 3 else ""

        if not action_json and sys.stdin and not sys.stdin.isatty():
            try:
                action_json = sys.stdin.read().strip()
            except Exception:
                pass

        if not action_json:
            _print_json("error", error="No action provided. Usage: delux-judge <action_json> [result] [request]")
            sys.exit(1)

        output = judge_action(action_json, result, request)
        print(output)

    except KeyboardInterrupt:
        _print_json("error", error="Interrupted by user (Ctrl+C)")
        sys.exit(130)
    except Exception:
        _print_json("error", error=f"Unhandled CLI error: {traceback.format_exc()[:1000]}")
        sys.exit(1)
