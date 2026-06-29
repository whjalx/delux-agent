#!/usr/bin/env bash
set -euo pipefail

QUERY="${1:-}"
SEARCH_PATH="${2:-.}"

# --- helpers ---
json_escape() {
    local s="${1-}"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

# --- validate input ---
if [[ -z "$QUERY" ]]; then
    printf '{"status":"error","error":"query is required"}\n'
    exit 0
fi

if [[ ! -e "$SEARCH_PATH" ]]; then
    printf '{"status":"error","error":"path not found: %s"}\n' "$(json_escape "$SEARCH_PATH")"
    exit 0
fi

if [[ ! -r "$SEARCH_PATH" ]]; then
    printf '{"status":"error","error":"permission denied: %s"}\n' "$(json_escape "$SEARCH_PATH")"
    exit 0
fi

# --- build exclude arguments ---
EXCLUDE_DIRS=('node_modules' '.git' '__pycache__' '.venv' 'venv' 'dist' 'build' 'target')

rg_excludes=()
grep_excludes=()
for d in "${EXCLUDE_DIRS[@]}"; do
    rg_excludes+=(--glob "!${d}")
    grep_excludes+=(--exclude-dir="$d")
done

MAX_LINES=200

# --- search ---
if command -v rg &>/dev/null; then
    raw=$(rg --smart-case --max-columns 200 --no-heading --line-number \
             "${rg_excludes[@]}" -- "$QUERY" "$SEARCH_PATH" 2>/dev/null \
             | head -n "$MAX_LINES" || true)
elif command -v grep &>/dev/null; then
    raw=$(grep -rnI --color=never "${grep_excludes[@]}" -- "$QUERY" "$SEARCH_PATH" 2>/dev/null \
             | head -n "$MAX_LINES" || true)
else
    printf '{"status":"error","error":"ripgrep not installed and grep not available"}\n'
    exit 0
fi

# --- build JSON ---
if [[ -z "$raw" ]]; then
    printf '{"status":"ok","data":{"query":"%s","path":"%s","total_matches":0,"results":[]}}\n' \
        "$(json_escape "$QUERY")" "$(json_escape "$SEARCH_PATH")"
    exit 0
fi

# Parse raw output:  file:line:content   (rg -n) or   file:line:content   (grep)
declare -A file_matches
declare -a file_order
total=0

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    # rg --no-heading and grep -rn both produce: file:line:text
    # Use first colon as file separator, second as line separator
    file="${line%%:*}"
    rest="${line#*:}"
    linenum="${rest%%:*}"
    content="${rest#*:}"

    # Skip if we couldn't parse
    [[ -z "$file" || -z "$linenum" ]] && continue

    # Deduplicate: only add if not already seen for this file+line combo
    key="${file}:${linenum}"
    if [[ -z "${file_matches["$file"]+x}" ]]; then
        file_order+=("$file")
        file_matches["$file"]=""
    fi

    escaped_content="$(json_escape "$content")"
    match_obj="{\"line\":${linenum},\"content\":\"${escaped_content}\"}"
    file_matches["$file"]+="${match_obj},"$'\n'
    total=$((total + 1))
done <<< "$raw"

# Build results array
results_json="["
first_file=1
for f in "${file_order[@]}"; do
    if [[ $first_file -eq 1 ]]; then first_file=0; else results_json+=","; fi
    results_json+="{\"file\":\"$(json_escape "$f")\",\"matches\":["
    # Rebuild matches for this file (trim trailing comma)
    m="${file_matches[$f]}"
    m="${m%,$'\n'}"
    # Replace the newline separators with commas
    m="${m//$'\n',/,}"
    results_json+="$m"
    results_json+="]}"
done
results_json+="]"

printf '{"status":"ok","data":{"query":"%s","path":"%s","total_matches":%d,"results":%s}}\n' \
    "$(json_escape "$QUERY")" "$(json_escape "$SEARCH_PATH")" "$total" "$results_json"

unset file_matches file_order
