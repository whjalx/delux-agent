#!/bin/bash

QUERY="$1"
PATH_TO_SEARCH="${2:-.}"

if [ -z "$QUERY" ]; then
    echo "Usage: search-expert <query> [path]"
    exit 1
fi

echo "🔍 Searching for '$QUERY' in $PATH_TO_SEARCH..."

# --smart-case: Mayúsculas/minúsculas inteligente
# --glob: Excluir carpetas pesadas explícitamente por si no hay .gitignore
# --max-columns 200: No traer líneas ultra largas (minificadas)
# --heading: Agrupar por archivo
# --line-number: Mostrar línea
# -C 1: Mostrar una línea de contexto arriba y abajo
rg --smart-case \
   --max-columns 200 \
   --glob '!node_modules/*' \
   --glob '!.git/*' \
   --glob '!__pycache__/*' \
   --heading \
   --line-number \
   -C 1 \
   "$QUERY" "$PATH_TO_SEARCH" | head -n 100 # Limitar a 100 líneas para proteger el contexto
