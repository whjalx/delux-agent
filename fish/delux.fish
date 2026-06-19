function delux --description "Run Delux shell AI agent"
    # Try to find the venv directory
    set -l venv_dir ""

    # Check DELUX_VENV env variable first
    if test -n "$DELUX_VENV"
        set venv_dir "$DELUX_VENV"
    end

    # Try common locations
    if test -z "$venv_dir"
        for loc in \
            (dirname (status --current-filename))/../.venv \
            $HOME/.local/share/delux/.venv \
            $HOME/.delux/.venv \
            $HOME/.local/delux/.venv
            if test -d "$loc"
                set venv_dir "$loc"
                break
            end
        end
    end

    # Run delux
    if test -n "$venv_dir" -a -x "$venv_dir/bin/delux"
        command "$venv_dir/bin/delux" $argv
    else if command -v delux &>/dev/null
        command delux $argv
    else
        echo "Delux not found. Run:" >&2
        echo "  curl -fsSL https://raw.githubusercontent.com/anomalyco/delux-agent/main/install.sh | bash" >&2
        return 1
    end
end
