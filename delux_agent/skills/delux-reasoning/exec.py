#!/usr/bin/env python3
import sys
import json
import re

MAX_INPUT_LENGTH = 10_000

PROBLEM_PATTERNS = [
    {
        'category': 'performance',
        'keywords': ['slow', 'performance', 'latency', 'bottleneck', 'hang', 'timeout', 'lag', 'delay', 'throughput', 'profiling'],
        'sub_problems': [
            {'question': 'Is CPU or memory saturated?', 'approach': 'Check top/htop/free', 'confidence': 0.95, 'fallback': 'Check dmesg for OOM kills'},
            {'question': 'Is disk I/O the bottleneck?', 'approach': 'Run iostat -x 1 or iotop', 'confidence': 0.85, 'fallback': 'Check disk usage with df'},
            {'question': 'Is there a network issue?', 'approach': 'Check netstat/ss and ping', 'confidence': 0.80, 'fallback': 'Check systemd-networkd or NetworkManager logs'},
            {'question': 'Are there application-level issues?', 'approach': 'Check application logs and journalctl', 'confidence': 0.75, 'fallback': 'Restart the service'},
        ],
        'conclusion': 'Systematic check of CPU, memory, disk, network, and application logs will identify the bottleneck.',
        'next_action': 'shell',
    },
    {
        'category': 'deployment',
        'keywords': ['deploy', 'deployment', 'release', 'ship', 'publish', 'rollout', 'dockerize', 'ci/cd', 'pipeline'],
        'sub_problems': [
            {'question': 'What is the target environment?', 'approach': 'Check deployment config and infrastructure', 'confidence': 0.95, 'fallback': 'List all known environments'},
            {'question': 'What artifacts need to be deployed?', 'approach': 'Check build output, Docker images, or binaries', 'confidence': 0.90, 'fallback': 'Run the build first'},
            {'question': 'What is the deployment strategy?', 'approach': 'Check CI/CD pipeline, scripts, or tools', 'confidence': 0.85, 'fallback': 'Default to rolling update if not specified'},
            {'question': 'Are there pre-deployment checks?', 'approach': 'Run tests, lint, type checks, and smoke tests', 'confidence': 0.80, 'fallback': 'Skip checks and deploy with monitoring'},
        ],
        'conclusion': 'Deployment requires identifying environment, building artifacts, choosing a strategy, and running pre-deployment checks.',
        'next_action': 'read_file',
    },
    {
        'category': 'bug',
        'keywords': ['bug', 'error', 'crash', 'fail', 'broken', 'fix', 'exception', 'defect', 'fault', 'traceback', 'stacktrace'],
        'sub_problems': [
            {'question': 'What is the exact error message?', 'approach': 'Read error logs, stack traces, and reproduction steps', 'confidence': 0.95, 'fallback': 'Read the code around the failing area'},
            {'question': 'Can the bug be reproduced?', 'approach': 'Run the failing test or reproduce the scenario', 'confidence': 0.90, 'fallback': 'Examine the code statically'},
            {'question': 'What is the root cause?', 'approach': 'Trace the code path from trigger to error', 'confidence': 0.85, 'fallback': 'Add debug logging'},
            {'question': 'What is the safest fix?', 'approach': 'Propose minimal change, test, and verify', 'confidence': 0.80, 'fallback': 'Larger refactor if necessary'},
        ],
        'conclusion': 'Bug fixes require understanding the error, reproducing it, finding the root cause, and applying a minimal safe fix.',
        'next_action': 'read_file',
    },
    {
        'category': 'refactor',
        'keywords': ['refactor', 'rewrite', 'restructure', 'clean', 'improve', 'reorganize', 'decouple', 'simplify', 'modernize'],
        'sub_problems': [
            {'question': 'What is the current structure?', 'approach': 'Read the target files and understand the architecture', 'confidence': 0.95, 'fallback': 'Skim the code and identify main components'},
            {'question': 'What patterns need to change?', 'approach': 'Identify anti-patterns, duplication, and complexity', 'confidence': 0.88, 'fallback': 'Focus on the most critical files first'},
            {'question': 'What tests exist?', 'approach': 'Find and run existing tests to establish baseline', 'confidence': 0.85, 'fallback': 'Write characterization tests'},
            {'question': 'How to refactor incrementally?', 'approach': 'Plan small, reversible steps with test coverage', 'confidence': 0.82, 'fallback': 'Do a single large refactor with careful review'},
        ],
        'conclusion': 'Refactoring requires understanding current structure, identifying improvements, establishing test safety nets, and making incremental changes.',
        'next_action': 'read_file',
    },
    {
        'category': 'security',
        'keywords': ['security', 'vulnerability', 'auth', 'authentication', 'authorization', 'injection', 'xss', 'csrf', 'encrypt', 'ssl', 'tls', 'certificate', 'secret', 'token', 'password', 'exploit'],
        'sub_problems': [
            {'question': 'What is the attack surface?', 'approach': 'Identify all input points, APIs, and exposed services', 'confidence': 0.95, 'fallback': 'Review the entire codebase for input handling'},
            {'question': 'Are there known vulnerabilities?', 'approach': 'Check CVE databases, dependency audits, and security advisories', 'confidence': 0.90, 'fallback': 'Run a static analysis security tool'},
            {'question': 'Is authentication and authorization correct?', 'approach': 'Review auth middleware, token validation, and permission checks', 'confidence': 0.88, 'fallback': 'Audit access control lists manually'},
            {'question': 'Are secrets and sensitive data protected?', 'approach': 'Check for hardcoded secrets, env var handling, and encryption', 'confidence': 0.85, 'fallback': 'Scan commit history for exposed secrets'},
        ],
        'conclusion': 'Security analysis requires identifying attack surface, checking vulnerabilities, reviewing auth, and ensuring secrets protection.',
        'next_action': 'read_file',
    },
    {
        'category': 'configuration',
        'keywords': ['config', 'configuration', 'setup', 'settings', 'environment', '.env', 'properties', 'options', 'parameters', 'preferences'],
        'sub_problems': [
            {'question': 'What configuration exists?', 'approach': 'Identify all config files, env vars, and CLI flags', 'confidence': 0.95, 'fallback': 'Scan the repository for common config file patterns'},
            {'question': 'What configuration is missing or incorrect?', 'approach': 'Compare actual config against expected/required values', 'confidence': 0.88, 'fallback': 'Check defaults and documentation'},
            {'question': 'Are there environment-specific issues?', 'approach': 'Check dev, staging, and production config differences', 'confidence': 0.85, 'fallback': 'Assume production environment'},
            {'question': 'How to apply configuration safely?', 'approach': 'Validate changes, use atomic updates, and test first', 'confidence': 0.82, 'fallback': 'Backup config before changes'},
        ],
        'conclusion': 'Configuration issues require identifying current config, finding gaps, checking environment specifics, and applying changes safely.',
        'next_action': 'read_file',
    },
]


def _match_patterns(task):
    task_lower = task.lower()
    best_match = None
    best_score = 0
    for pattern in PROBLEM_PATTERNS:
        score = sum(1 for kw in pattern['keywords'] if kw in task_lower)
        if score > best_score:
            best_score = score
            best_match = pattern
    return best_match, best_score


def _reason(task):
    clean_task = re.sub(r'^analyze:\s*', '', task, flags=re.IGNORECASE).strip()
    if not clean_task:
        clean_task = task

    pattern, match_score = _match_patterns(clean_task)

    if pattern and match_score >= 1:
        sub_problems = pattern['sub_problems']
        conclusion = pattern['conclusion']
        next_action = pattern['next_action']
        overall_confidence = round(min(sub['confidence'] for sub in sub_problems), 2)
        category = pattern['category']
    else:
        category = 'general'
        words = clean_task.split()
        sub_problems = [
            {'question': 'Understanding the core request', 'approach': 'Parse intent, extract implicit requirements', 'confidence': 0.90, 'fallback': 'Ask clarifying questions'},
            {'question': 'What information is needed?', 'approach': 'Search docs, code, and context for relevant information', 'confidence': 0.85, 'fallback': 'Use best available knowledge'},
            {'question': 'What is the execution plan?', 'approach': 'Break into specific tool calls and verify each step', 'confidence': 0.80, 'fallback': 'Try the most likely approach first'},
            {'question': 'How to validate the result?', 'approach': 'Check output, run tests, and verify against requirements', 'confidence': 0.75, 'fallback': 'Manual inspection'},
        ]
        conclusion = f'Delux reasoning engaged for: {clean_task[:150]}'
        next_action = 'read_file' if any(kw in clean_task.lower() for kw in ['file', 'code', 'read', 'check']) else 'shell'
        overall_confidence = 0.85

    reasoning_trace = ' → '.join(sp['question'] for sp in sub_problems)

    return {
        'analysis': {
            'problem_statement': clean_task,
            'category': category,
            'sub_problems': sub_problems,
            'conclusion': conclusion,
            'confidence': overall_confidence,
            'next_action': next_action,
        },
        'reasoning_trace': reasoning_trace,
    }


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
            print(json.dumps({
                'status': 'ok',
                'data': {
                    'usage': 'exec.py <task description>',
                    'description': 'Structured reasoning engine that analyzes problems into sub-problems',
                }
            }))
            return

        task = ' '.join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ''

        if not task:
            print(json.dumps({
                'status': 'ok',
                'data': {
                    'analysis': {
                        'problem_statement': '',
                        'category': 'none',
                        'sub_problems': [],
                        'conclusion': 'No task provided',
                        'confidence': 0.0,
                        'next_action': 'final',
                    },
                    'reasoning_trace': 'No task to analyze',
                }
            }))
            return

        if len(task) > MAX_INPUT_LENGTH:
            task = task[:MAX_INPUT_LENGTH]

        result = _reason(task)
        print(json.dumps({'status': 'ok', 'data': result}))

    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'status': 'error', 'error': str(e)}))
