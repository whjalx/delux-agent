# delux fish completion
complete -c delux -n "__fish_use_subcommand" -a "setup" -d "Configure AI providers and models"
complete -c delux -n "__fish_use_subcommand" -a "ide" -d "Open interactive terminal IDE"

complete -c delux -n "__fish_use_subcommand" -l help -s h -d "Show help message"
complete -c delux -n "__fish_use_subcommand" -l cwd -d "Working directory for shell commands" -r
complete -c delux -n "__fish_use_subcommand" -l home -d "DELUX_HOME workspace" -r
complete -c delux -n "__fish_use_subcommand" -l max-steps -d "Maximum autonomous action steps" -r
complete -c delux -n "__fish_use_subcommand" -l quiet -d "Only print the final answer"
complete -c delux -n "__fish_use_subcommand" -l init -d "Create memory, docs, and skills directories"
complete -c delux -n "__fish_use_subcommand" -l context -d "Print loaded context"
complete -c delux -n "__fish_use_subcommand" -l new-skill -d "Create a blank skill" -r
complete -c delux -n "__fish_use_subcommand" -l summary -d "Summary for --new-skill" -r

# setup subcommand
complete -c delux -n "__fish_seen_subcommand_from setup" -l home -d "DELUX_HOME workspace" -r

# Directory completions for --cwd
complete -c delux -n "__fish_seen_subcommand_from --cwd" -a "(__fish_complete_directories)" -d "Directory"

# Skill completions for --new-skill
complete -c delux -n "__fish_seen_subcommand_from --new-skill" -x
