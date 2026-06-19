# delux bash completion
_delux() {
    local cur prev opts subcommands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    subcommands="setup ide"
    opts="-h --help --cwd --home --max-steps --quiet --init --context --new-skill --summary"

    # If previous word is --cwd, complete directories
    if [[ "$prev" == "--cwd" ]]; then
        COMPREPLY=( $(compgen -d -- "$cur") )
        return
    fi

    # If previous word is --home or --new-skill or --summary, no completion
    if [[ "$prev" == "--home" || "$prev" == "--new-skill" || "$prev" == "--summary" || "$prev" == "--max-steps" ]]; then
        return
    fi

    # Complete subcommands
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$subcommands" -- "$cur") )
        return
    fi

    # Complete options
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}

complete -F _delux delux
