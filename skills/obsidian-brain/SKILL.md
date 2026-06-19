# Obsidian Learning Brain

Summary: Gestiona la Base de Conocimiento (Knowledge Base) y el aprendizaje profundo del agente. NO es para la memoria personal o general del usuario. Es el cerebro de investigación del agente: ideal para guardar notas técnicas, ejemplos de código, guías, documentación o hallazgos que sirven como fuente de información estructurada para el agente y el usuario. Utiliza notas Markdown compatibles con el Knowledge Graph de Obsidian.

## Usage
- `add <topic> "<content>" [-l <link1> <link2>]`: Crea o agrega contenido a una nota sobre un tema específico, creando enlaces automáticos.
- `read <topic>`: Lee el contenido completo de una nota de la memoria.
- `list`: Lista todas las notas guardadas en el cerebro del agente.

## Ejemplos
- `./exec.py add ProyectoAlpha "Iniciando nueva fase de desarrollo" -l Desarrollo Planificacion`
- `./exec.py read ProyectoAlpha`

## Files Touched
- Crea y modifica archivos `.md` en la carpeta `~/.delux/obsi` (o la ruta especificada en `OBSIDIAN_VAULT`).
