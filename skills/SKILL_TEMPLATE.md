# SKILL TEMPLATE — Cómo crear una skill para Delux

Cada skill vive en su propio directorio dentro de `skills/<nombre-de-la-skill>/`.
Toda skill tiene **3 partes obligatorias**:

## 1. `SKILL.md` — Documentación (obligatorio)

Archivo Markdown que describe qué hace la skill, cuándo usarla, y cómo responde.

Estructura exacta que debe tener:

```markdown
# skill:<nombre-de-la-skill>
## Summary
Una línea describiendo qué hace esta skill.

## When To Use
- Caso de uso 1
- Caso de uso 2

## Usage
<nombre> <argumentos>

## Steps
1. Paso 1
2. Paso 2

## Response Examples (OBLIGATORIO)

### Agent invoca la skill
```json
{"action":"run_skill","skill":"<nombre>","args":"<argumentos>","timeout":30}
```

### Skill devuelve resultado
```json
{
  "campo": "valor",
  "status": "ok"
}
```

### Prompt injection example (para few-shot learning, OBLIGATORIO)
```
--- <nombre> example ---
USER: "<ejemplo de input del usuario>"
AGENT: {"action":"run_skill","skill":"<nombre>","args":"<args>","timeout":30}
RESULT: {"campo": "valor", "status": "ok"}
NEXT ACTION: {"action":"shell/final/read_file","..."}
```

## Caveats
- Advertencias importantes
```

## 2. `exec.py` (o `exec.bash`, `exec.go`, etc.) — Script ejecutable (recomendado)

Script que ejecuta la lógica de la skill. Recibe argumentos por línea de comandos y devuelve JSON por stdout.

Estructura mínima:

```python
import sys, json

def mi_skill(args: list[str]) -> dict:
    # Lógica aquí
    return {"status": "ok", "result": "hecho"}

if __name__ == "__main__":
    args = sys.argv[1:]
    print(json.dumps(mi_skill(args)))
```

## 3. Response JSON (obligatorio para todas las skills así no tengan exec)

Toda skill DEBE documentar en `SKILL.md`:
- El JSON **entrada**: qué envía el agente para invocarla (`{"action":"run_skill","skill":"...","args":"..."}`)
- El JSON **salida**: qué devuelve la skill cuando se ejecuta
- Un **ejemplo de inyección**: el flujo completo USER → AGENT → RESULT → NEXT ACTION

Esto permite que hasta modelos pequeños aprendan el formato exacto viendo el archivo.

## Regla de creación automática

Cuando el agente necesita crear una skill nueva:
1. Lee este archivo (SKILL_TEMPLATE) para entender el formato
2. Lee alguna skill existente en SKILLS como ejemplo de referencia
3. Usa `create_skill` para crear el directorio y SKILL.md automáticamente
4. Si aplica, usa `write_file` para crear `exec.py` con la lógica
5. Guarda la skill en memoria con `remember`
