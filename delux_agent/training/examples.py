"""Few-shot execution examples for Delux.
Injected into the system prompt to teach small models the exact XML action format."""

# ── Action format examples (injected into system prompt) ─────────────────────

FEW_SHOT_EXAMPLES = """
--- FEW-SHOT EXECUTION EXAMPLES ---
These are real examples of how Delux responds. Learn the XML action format from them.

=== Example 1: Simple shell command ===
USER: list files in current directory
AGENT: <action>shell</action>
<command>ls -la</command>
<timeout>30</timeout>
RESULT: total 42
drwxr-xr-x ...
AGENT: <action>final</action>
<message>Found 12 files and 3 directories</message>

=== Example 2: Read and analyze a file ===
USER: show me the config file
AGENT: <action>read_file</action>
<path>/etc/hostname</path>
RESULT: myhost
AGENT: <action>final</action>
<message>Hostname is: myhost</message>

=== Example 3: Multi-step with skill ===
USER: check if the server is healthy
AGENT: <action>shell</action>
<command>uptime</command>
<timeout>30</timeout>
RESULT: 10:30 up 3 days, 2 users
AGENT: <action>run_skill</action>
<skill>delux-net-check</skill>
<args>--quick</args>
<timeout>30</timeout>
RESULT: All services OK
AGENT: <action>final</action>
<message>Server has been up 3 days, all services healthy</message>

=== Example 4: File edit ===
USER: fix the typo in README
AGENT: <action>read_file</action>
<path>README.md</path>
RESULT: # Delux
Welcom to the agent...
AGENT: <action>edit_file</action>
<path>README.md</path>
<old_str>Welcom to</old_str>
<new_str>Welcome to</new_str>
RESULT: Edited README.md (1 occurrence)
AGENT: <action>final</action>
<message>Fixed typo 'Welcom' -> 'Welcome' in README.md</message>

=== Example 5: Using reasoning skill ===
USER: debug why nginx won't start
AGENT: <action>run_skill</action>
<skill>delux-reasoning</skill>
<args>analyze: nginx won't start</args>
<timeout>30</timeout>
RESULT: analysis: nginx may not be installed. Next step: check if nginx exists.
AGENT: <action>shell</action>
<command>systemctl status nginx 2>&1</command>
<timeout>30</timeout>
RESULT: Unit nginx.service not found
AGENT: <action>shell</action>
<command>dnf install -y nginx</command>
<timeout>60</timeout>
RESULT: Installed nginx
AGENT: <action>final</action>
<message>Nginx was not installed. Installed it successfully.</message>

=== Example 6: Using codex skill ===
USER: review src/app.js for bugs
AGENT: <action>run_skill</action>
<skill>delux-codex</skill>
<args>src/app.js</args>
<timeout>30</timeout>
RESULT: mode: analyze, target: src/app.js, status: ready
AGENT: <action>read_file</action>
<path>src/app.js</path>
RESULT: function add(a,b){return a+b}
AGENT: <action>final</action>
<message>Code looks clean. Single function with no obvious bugs.</message>

=== Example 7: Using browser skill ===
USER: get the title of example.com
AGENT: <action>run_skill</action>
<skill>delux-browser</skill>
<args>text https://example.com</args>
<timeout>30</timeout>
RESULT: Page title: Example Domain
AGENT: <action>final</action>
<message>The page title is 'Example Domain'</message>

=== Example 8: Using oracle skill ===
USER: what do we know about the server?
AGENT: <action>run_skill</action>
<skill>delux-oracle</skill>
<args>server configuration</args>
<timeout>30</timeout>
RESULT: Server IP: 192.168.1.100 (from memory)
AGENT: <action>final</action>
<message>Server IP is 192.168.1.100 (from memory)</message>

=== Example 9: Error recovery ===
USER: compile the project
AGENT: <action>shell</action>
<command>make</command>
<timeout>60</timeout>
RESULT: ERROR: make: command not found
AGENT: <action>shell</action>
<command>dnf install -y make</command>
<timeout>60</timeout>
RESULT: Installed make
AGENT: <action>shell</action>
<command>make</command>
<timeout>60</timeout>
RESULT: Build complete
AGENT: <action>final</action>
<message>Installed make and compiled the project</message>

=== Example 10: Remember fact ===
USER: my database password is in ~/.db_secret
AGENT: <action>remember</action>
<note>Database password stored in ~/.db_secret</note>
RESULT: Saved note to memory/memory.md
AGENT: <action>final</action>
<message>Remembered where the database password is stored</message>

=== Example 11: Verification workflow ===
USER: create a python script that counts lines in a file
AGENT: <action>write_file</action>
<path>/tmp/line_counter.py</path>
<content>import sys
if len(sys.argv) > 1:
    with open(sys.argv[1]) as f:
        print(f'Lines: {len(f.readlines())}')</content>
RESULT: Wrote /tmp/line_counter.py
AGENT: <action>verify_file</action>
<path>/tmp/line_counter.py</path>
RESULT: SUCCESS: /tmp/line_counter.py passed .py syntax check. OK
AGENT: <action>shell</action>
<command>echo 'hello\nworld\nfoo' > /tmp/test_data.txt && python3 /tmp/line_counter.py /tmp/test_data.txt > /tmp/verify.log 2>&1; cat /tmp/verify.log</command>
<timeout>15</timeout>
RESULT: Lines: 3
AGENT: <action>final</action>
<message>Created line_counter.py, verified syntax, tested with sample data, output correct</message>

=== Example 12: Multi-step with task tracking ===
USER: create index.html, style.css, and script.js for a landing page
AGENT: <action>set_tasks</action>
<tasks>["Create index.html", "Create style.css", "Create script.js"]</tasks>
RESULT: SUCCESS: Created 3 tasks.
AGENT: <action>write_file</action>
<path>index.html</path>
<content><!DOCTYPE html>
<html><head><title>Landing</title></head>
<body><h1>Welcome</h1></body></html></content>
RESULT: Wrote index.html
AGENT: <action>task_done</action>
<task>Create index.html</task>
RESULT: SUCCESS: Task 'Create index.html' completed. 2 task(s) remaining.
AGENT: <action>write_file</action>
<path>style.css</path>
<content>body { font-family: sans-serif; color: #333; }</content>
RESULT: Wrote style.css
AGENT: <action>task_done</action>
<task>Create style.css</task>
RESULT: SUCCESS: Task 'Create style.css' completed. 1 task(s) remaining.
AGENT: <action>write_file</action>
<path>script.js</path>
<content>console.log('ready');</content>
RESULT: Wrote script.js
AGENT: <action>task_done</action>
<task>Create script.js</task>
RESULT: SUCCESS: Task 'Create script.js' completed. 0 task(s) remaining.
AGENT: <action>final</action>
<summary>Created 3 files for landing page</summary>
<message>Created index.html, style.css, and script.js for a landing page</message>
"""


def get_few_shot_examples() -> str:
    return FEW_SHOT_EXAMPLES
