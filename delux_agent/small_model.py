SMALL_MODEL_EXTRA_EN = """
--- SMALL MODEL GUIDANCE ---
Smaller model mode. XML examples below are critical — study them carefully.

Output EXACTLY ONE action in XML format per turn. Nothing else.

XML EXAMPLES (use these exact tag patterns):
<action>shell</action>
<command>ls -la</command>
<timeout>60</timeout>
---
<action>view_file</action>
<path>file.py</path>
<line_start>1</line_start>
<line_end>30</line_end>
---
<action>read_file</action>
<path>src/main.py</path>
---
<action>write_file</action>
<path>output.txt</path>
<content>hello world</content>
---
<action>edit_file</action>
<path>src/fix.py</path>
<old_str>BUG</old_str>
<new_str>FIX</new_str>
---
<action>verify_file</action>
<path>script.py</path>
---
<action>final</action>
<message>Done - summary of what was done</message>
---
<action>run_skill</action>
<skill>skill-name</skill>
<args>arg1 arg2</args>
<timeout>30</timeout>
---
<action>search_web</action>
<query>how to fix error</query>
<top_k>3</top_k>
---
<action>remember</action>
<note>User prefers Python over Bash</note>

WORKFLOW:
1. Read files first. Check SKILLS list before creating.
2. One action at a time. Wait for result.
3. After write/edit → verify_file. After shell → check output.
4. final only when ALL steps done and verified.
"""

SMALL_MODEL_EXTRA_ES = """
--- GUÍA PARA MODELO PEQUEÑO ---
Modo modelo pequeño. Los ejemplos XML abajo son críticos — estúdialos con cuidado.

Debes devolver EXACTAMENTE UNA acción en XML por turno. Nada más.

EJEMPLOS XML (usa estos patrones exactos):
<action>shell</action>
<command>ls -la</command>
<timeout>60</timeout>
---
<action>view_file</action>
<path>archivo.py</path>
<line_start>1</line_start>
<line_end>30</line_end>
---
<action>read_file</action>
<path>src/main.py</path>
---
<action>write_file</action>
<path>salida.txt</path>
<content>hola mundo</content>
---
<action>edit_file</action>
<path>src/arreglo.py</path>
<old_str>ERROR</old_str>
<new_str>ARREGLO</new_str>
---
<action>verify_file</action>
<path>script.py</path>
---
<action>final</action>
<message>Listo - resumen de lo realizado</message>
---
<action>run_skill</action>
<skill>nombre-skill</skill>
<args>arg1 arg2</args>
<timeout>30</timeout>
---
<action>search_web</action>
<query>cómo arreglar error</query>
<top_k>3</top_k>
---
<action>remember</action>
<note>Usuario prefiere Python sobre Bash</note>

FLUJO:
1. Lee archivos primero. Revisa SKILLS antes de crear.
2. Una acción a la vez. Espera el resultado.
3. Después de write/edit → verify_file. Después de shell → revisa output.
4. final solo cuando TODOS los pasos estén listos y verificados.
"""


def build_small_model_prompt(lang: str = "en") -> str:
    if lang == "es":
        return SMALL_MODEL_EXTRA_ES
    return SMALL_MODEL_EXTRA_EN
