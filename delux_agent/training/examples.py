"""Few-shot execution examples for Delux.
Injected into the system prompt to teach small models the exact XML action format."""

# ── Action format examples (injected into system prompt) ─────────────────────

FEW_SHOT_EXAMPLES = """
--- FEW-SHOT EXAMPLES ---

=== Example 1: Simple command ===
USER: list files
AGENT: <action>shell</action>
<command>ls -la</command>
<timeout>30</timeout>
RESULT: total 42
AGENT: <action>final</action>
<message>Found 12 files and 3 directories</message>

=== Example 2: File edit ===
USER: fix typo in README
AGENT: <action>read_file</action>
<path>README.md</path>
RESULT: # Delux\nWelcom to the agent...
AGENT: <action>edit_file</action>
<path>README.md</path>
<old_str>Welcom to</old_str>
<new_str>Welcome to</new_str>
RESULT: Edited README.md (1 occurrence)
AGENT: <action>final</action>
<message>Fixed typo 'Welcom' -> 'Welcome' in README.md</message>

=== Example 3: Verification workflow ===
USER: create a python script that counts lines
AGENT: <action>write_file</action>
<path>/tmp/line_counter.py</path>
<content>import sys
if len(sys.argv) > 1:
    with open(sys.argv[1]) as f:
        print(f'Lines: {len(f.readlines())}')</content>
RESULT: Wrote /tmp/line_counter.py
AGENT: <action>verify_file</action>
<path>/tmp/line_counter.py</path>
RESULT: SUCCESS: syntax OK
AGENT: <action>shell</action>
<command>echo 'hello\nworld' > /tmp/test.txt && python3 /tmp/line_counter.py /tmp/test.txt</command>
<timeout>15</timeout>
RESULT: Lines: 2
AGENT: <action>final</action>
<message>Created line_counter.py, syntax verified, functional test passed</message>

=== Example 4: Error recovery ===
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

=== Example 5: Explain mid-task with info tag ===
USER: set up nginx with a custom config
AGENT: <action>shell</action>
<command>which nginx</command>
<timeout>10</timeout>
<info>First I'll check if nginx is installed</info>
RESULT: /usr/sbin/nginx
AGENT: <action>write_file</action>
<path>/etc/nginx/sites-available/myapp</path>
<content>server { listen 80; server_name example.com; }</content>
<info>Nginx is installed. Now creating the custom config</info>
RESULT: Created /etc/nginx/sites-available/myapp
AGENT: <action>final</action>
<message>Nginx configured with custom site. Config at /etc/nginx/sites-available/myapp</message>

=== Example 6: Honest failure report ===
USER: install and configure redis
AGENT: <action>shell</action>
<command>which redis-server</command>
<timeout>10</timeout>
RESULT: ERROR: command not found
AGENT: <action>shell</action>
<command>apt-get install -y redis-server</command>
<timeout>60</timeout>
RESULT: ERROR: Permission denied (no sudo)
AGENT: <action>final</action>
<summary>Cannot install redis: requires sudo/root privileges</summary>
<message>No puedo instalar Redis porque se requieren privilegios de administrador</message>

=== Example 7: Multi-step with task tracking ===
USER: create index.html, style.css, and script.js
AGENT: <action>set_tasks</action>
<tasks>["Create index.html", "Create style.css", "Create script.js"]</tasks>
RESULT: SUCCESS: Created 3 tasks.
AGENT: <action>write_file</action>
<path>index.html</path>
<content><!DOCTYPE html><html><body><h1>Welcome</h1></body></html></content>
RESULT: Wrote index.html
AGENT: <action>task_done</action>
<task>Create index.html</task>
RESULT: SUCCESS: 2 remaining
AGENT: <action>write_file</action>
<path>style.css</path>
<content>body { color: #333; }</content>
RESULT: Wrote style.css
AGENT: <action>task_done</action>
<task>Create style.css</task>
RESULT: SUCCESS: 1 remaining
AGENT: <action>write_file</action>
<path>script.js</path>
<content>console.log('ready');</content>
RESULT: Wrote script.js
AGENT: <action>task_done</action>
<task>Create script.js</task>
RESULT: SUCCESS: 0 remaining
AGENT: <action>final</action>
<summary>Created 3 files for landing page</summary>
<message>Created index.html, style.css, and script.js</message>
"""


def get_few_shot_examples() -> str:
    return FEW_SHOT_EXAMPLES
