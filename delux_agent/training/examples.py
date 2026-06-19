"""Few-shot execution examples for Delux.
Injected into the system prompt to teach small models the exact JSON format."""

# ── Action format examples (injected into system prompt) ─────────────────────

FEW_SHOT_EXAMPLES = """
--- FEW-SHOT EXECUTION EXAMPLES ---
These are real examples of how Delux responds. Learn the JSON format from them.

=== Example 1: Simple shell command ===
USER: "list files in current directory"
AGENT: {"action":"shell","command":"ls -la","timeout":30}
RESULT: "total 42\ndrwxr-xr-x ..."
AGENT: {"action":"final","message":"Found 12 files and 3 directories"}

=== Example 2: Read and analyze a file ===
USER: "show me the config file"
AGENT: {"action":"read_file","path":"/etc/hostname"}
RESULT: "myhost"
AGENT: {"action":"final","message":"Hostname is: myhost"}

=== Example 3: Multi-step with skill ===
USER: "check if the server is healthy"
AGENT: {"action":"shell","command":"uptime","timeout":30}
RESULT: "10:30 up 3 days, 2 users"
AGENT: {"action":"run_skill","skill":"delux-net-check","args":"--quick","timeout":30}
RESULT: "All services OK"
AGENT: {"action":"final","message":"Server has been up 3 days, all services healthy"}

=== Example 4: File edit ===
USER: "fix the typo in README"
AGENT: {"action":"read_file","path":"README.md"}
RESULT: "# Delux\nWelcom to the agent..."
AGENT: {"action":"edit_file","path":"README.md","old_str":"Welcom to","new_str":"Welcome to"}
RESULT: "Edited README.md (1 occurrence)"
AGENT: {"action":"final","message":"Fixed typo 'Welcom' -> 'Welcome' in README.md"}

=== Example 5: Using reasoning skill ===
USER: "debug why nginx won't start"
AGENT: {"action":"run_skill","skill":"delux-reasoning","args":"analyze: nginx won't start","timeout":30}
RESULT: {"delux_reasoning":{"analysis":{"problem_statement":"nginx won't start","sub_problems":[{"question":"Is nginx installed?","confidence":0.95},{"question":"Is port 80 in use?","confidence":0.9}],"next_action":"shell"}}}
AGENT: {"action":"shell","command":"systemctl status nginx 2>&1","timeout":30}
RESULT: "Unit nginx.service not found"
AGENT: {"action":"shell","command":"dnf install -y nginx","timeout":60}
RESULT: "Installed nginx"
AGENT: {"action":"final","message":"Nginx was not installed. Installed it successfully."}

=== Example 6: Using codex skill ===
USER: "review src/app.js for bugs"
AGENT: {"action":"run_skill","skill":"delux-codex","args":"src/app.js","timeout":30}
RESULT: {"delux_codex":{"mode":"analyze","target":"src/app.js","status":"ready"}}
AGENT: {"action":"read_file","path":"src/app.js"}
RESULT: "function add(a,b){return a+b}"
AGENT: {"action":"final","message":"Code looks clean. Single function with no obvious bugs."}

=== Example 7: Using browser skill ===
USER: "get the title of example.com"
AGENT: {"action":"run_skill","skill":"delux-browser","args":"text https://example.com","timeout":30}
RESULT: {"action":"text","url":"https://example.com","status":"ok","text":"Example Domain\\n\\nThis domain is for use..."}
AGENT: {"action":"final","message":"The page title is 'Example Domain'"}

=== Example 8: Using oracle skill ===
USER: "what do we know about the server?"
AGENT: {"action":"run_skill","skill":"delux-oracle","args":"server configuration","timeout":30}
RESULT: {"delux_oracle":{"query":"server configuration","sources_checked":["memory","docs"],"findings":[{"source":"memory/memory.md","claim":"Server IP: 192.168.1.100"}]}}
AGENT: {"action":"final","message":"Server IP is 192.168.1.100 (from memory)"}

=== Example 9: Error recovery ===
USER: "compile the project"
AGENT: {"action":"shell","command":"make","timeout":60}
RESULT: "ERROR: make: command not found"
AGENT: {"action":"shell","command":"dnf install -y make","timeout":60}
RESULT: "Installed make"
AGENT: {"action":"shell","command":"make","timeout":60}
RESULT: "Build complete"
AGENT: {"action":"final","message":"Installed make and compiled the project"}

=== Example 10: Remember fact ===
USER: "my database password is in ~/.db_secret"
AGENT: {"action":"remember","note":"Database password stored in ~/.db_secret"}
RESULT: "Saved note to memory/memory.md"
AGENT: {"action":"final","message":"Remembered where the database password is stored"}

=== Example 11: Verification workflow ===
USER: "create a python script that counts lines in a file"
AGENT: {"action":"write_file","path":"/tmp/line_counter.py","content":"import sys\\nif len(sys.argv) > 1:\\n    with open(sys.argv[1]) as f:\\n        print(f'Lines: {len(f.readlines())}')"}
RESULT: "Wrote /tmp/line_counter.py"
AGENT: {"action":"verify_file","path":"/tmp/line_counter.py"}
RESULT: "SUCCESS: /tmp/line_counter.py passed .py syntax check. OK"
AGENT: {"action":"shell","command":"echo 'hello\\nworld\\nfoo' > /tmp/test_data.txt && python3 /tmp/line_counter.py /tmp/test_data.txt > /tmp/verify.log 2>&1; cat /tmp/verify.log","timeout":15}
RESULT: "Lines: 3"
AGENT: {"action":"final","message":"Created line_counter.py, verified syntax, tested with sample data, output correct"}
"""


def get_few_shot_examples() -> str:
    return FEW_SHOT_EXAMPLES
