#!/usr/bin/env bash
set -euo pipefail

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

arr_to_json() {
    local first=true
    local item
    for item in "$@"; do
        if $first; then first=false; else printf ','; fi
        printf '"%s"' "$(json_escape "$item")"
    done
}

# --- check git ---
if ! command -v git &>/dev/null; then
    printf '{"status":"error","error":"git not found in PATH"}\n'
    exit 0
fi

if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    printf '{"status":"error","error":"not a git repository"}\n'
    exit 0
fi

# --- branch ---
branch="detached"
if b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null); then
    branch="$b"
fi

# --- remote ---
remote=""
if r=$(git rev-parse --abbrev-ref @{u} 2>/dev/null); then
    remote="$r"
fi

# --- tags ---
all_tags=()
if tags_out=$(git tag --sort=-creatordate 2>/dev/null); then
    while IFS= read -r t; do
        [[ -n "$t" ]] && all_tags+=("$t")
    done <<< "$tags_out"
fi

# --- ahead / behind ---
ahead=0
behind=0
if [[ -n "$remote" ]]; then
    ahead=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)
    behind=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo 0)
fi

# --- staged / unstaged / untracked ---
staged=()
unstaged=()
untracked=()

if s_out=$(git diff --cached --name-only 2>/dev/null); then
    while IFS= read -r f; do [[ -n "$f" ]] && staged+=("$f"); done <<< "$s_out"
fi
if u_out=$(git diff --name-only 2>/dev/null); then
    while IFS= read -r f; do [[ -n "$f" ]] && unstaged+=("$f"); done <<< "$u_out"
fi
if t_out=$(git ls-files --others --exclude-standard 2>/dev/null); then
    while IFS= read -r f; do [[ -n "$f" ]] && untracked+=("$f"); done <<< "$t_out"
fi

# --- recent commits ---
commits_json="["
first=1
while IFS='§' read -r hash msg author date; do
    [[ -z "$hash" ]] && continue
    if [[ $first -eq 1 ]]; then first=0; else commits_json+=","; fi
    commits_json+="{\"hash\":\"$(json_escape "$hash")\",\"message\":\"$(json_escape "$msg")\",\"author\":\"$(json_escape "$author")\",\"date\":\"$(json_escape "$date")\"}"
done < <(git log -n 5 --format='%h§%s§%an§%ar' 2>/dev/null || true)
commits_json+="]"

# --- assemble JSON ---
printf '{"status":"ok","data":{'
printf '"branch":"%s",'        "$(json_escape "$branch")"
printf '"remote":"%s",'        "$(json_escape "$remote")"
printf '"tags":['; arr_to_json "${all_tags[@]}"; printf '],'
printf '"ahead":%d,'           "$ahead"
printf '"behind":%d,'          "$behind"
printf '"staged":[';  arr_to_json "${staged[@]}";   printf '],'
printf '"unstaged":['; arr_to_json "${unstaged[@]}"; printf '],'
printf '"untracked":['; arr_to_json "${untracked[@]}"; printf '],'
printf '"recent_commits":%s'   "$commits_json"
printf '}}\n'
