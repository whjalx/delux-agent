#!/usr/bin/env bash

if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo "ERROR: Not a git repository."
    exit 1
fi

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE=$(git rev-parse --abbrev-ref @{u} 2>/dev/null || echo "no upstream")
TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "no tags")

echo -e "${CYAN}${BOLD}=== Git Dashboard ===${RESET}"
echo -e "${BOLD}Branch:${RESET} ${GREEN}${BRANCH}${RESET} ${DIM}(upstream: ${REMOTE})${RESET}"
echo -e "${BOLD}Latest Tag:${RESET} ${YELLOW}${TAG}${RESET}"

# Ahead/Behind
if [ "$REMOTE" != "no upstream" ]; then
    AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null)
    BEHIND=$(git rev-list --count HEAD..@{u} 2>/dev/null)
    if [ "$AHEAD" -gt 0 ] || [ "$BEHIND" -gt 0 ]; then
        echo -e "${BOLD}Sync:${RESET} ${AHEAD} ahead, ${BEHIND} behind"
    fi
fi

echo -e "\n${BOLD}Status:${RESET}"
git status --short | sed 's/^/  /'

echo -e "\n${BOLD}Recent History:${RESET}"
git log -n 5 --oneline --graph --color | sed 's/^/  /'

echo ""
