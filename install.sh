#!/usr/bin/env bash
# Delux Agent - Universal Installer
# Works on: Linux, macOS, WSL
# Usage: curl -fsSL https://raw.githubusercontent.com/anomalyco/delux-agent/main/install.sh | bash
#    or: bash install.sh

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Defaults ────────────────────────────────────────────────────────────
INSTALL_DIR=""
INSTALL_MODE="venv"
RUN_SETUP="auto"
SKIP_SHELL="no"
INSTALL_BROWSER="no"
IS_TERMUX="no"

# ── Logging ─────────────────────────────────────────────────────────────
info()    { echo -e "  ${CYAN}ℹ${RESET}  $*"; }
success() { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
error()   { echo -e "  ${RED}✗${RESET}  $*" >&2; }

# ── Architecture Detection ────────────────────────────────────────────────
detect_architecture() {
    ARCH="$(uname -m)"
    case "$ARCH" in
        x86_64|amd64)  ARCH_LABEL="x86_64" ;;
        aarch64|arm64) ARCH_LABEL="ARM64"  ;;
        armv7l|armhf)  ARCH_LABEL="ARMv7"  ;;
        *)             ARCH_LABEL="$ARCH"  ;;
    esac
    info "Architecture: $ARCH_LABEL"
}

# ── Package Manager Detection ─────────────────────────────────────────────
detect_package_manager() {
    PKG_MGR=""
    PKG_UPDATE=""
    PKG_INSTALL=""
    for mgr_cmd in apt-get dnf pacman zypper apk brew; do
        if command -v "$mgr_cmd" &>/dev/null; then
            case "$mgr_cmd" in
                apt-get) PKG_MGR="apt"; PKG_UPDATE="apt-get update -qq"; PKG_INSTALL="apt-get install -y -qq" ;;
                dnf)     PKG_MGR="dnf"; PKG_UPDATE="dnf check-update -q || true"; PKG_INSTALL="dnf install -y" ;;
                pacman)  PKG_MGR="pacman"; PKG_UPDATE="pacman -Sy"; PKG_INSTALL="pacman -S --noconfirm" ;;
                zypper)  PKG_MGR="zypper"; PKG_UPDATE="zypper refresh"; PKG_INSTALL="zypper install -y" ;;
                apk)     PKG_MGR="apk"; PKG_UPDATE="apk update"; PKG_INSTALL="apk add" ;;
                brew)    PKG_MGR="brew"; PKG_UPDATE="brew update"; PKG_INSTALL="brew install" ;;
            esac
            info "Package manager: $PKG_MGR"
            return
        fi
    done
    warn "No supported package manager found. Install python3, pip, venv manually."
}

# ── System Dependencies ──────────────────────────────────────────────────
install_system_deps() {
    if [ -z "$PKG_MGR" ]; then return; fi
    info "Installing system dependencies..."
    case "$PKG_MGR" in
        apt) eval "sudo $PKG_UPDATE" 2>/dev/null || true
             eval "sudo $PKG_INSTALL python3 python3-pip python3-venv git curl" ;;
        dnf) eval "sudo $PKG_INSTALL python3 python3-pip python3-virtualenv git curl" ;;
        pacman) eval "sudo $PKG_INSTALL python python-pip python-virtualenv git curl" ;;
        zypper) eval "sudo $PKG_INSTALL python3 python3-pip python3-virtualenv git curl" ;;
        apk) eval "sudo $PKG_INSTALL python3 py3-pip git curl" ;;
        brew) eval "$PKG_INSTALL python3 git curl" ;;
    esac
    success "System dependencies installed"
}

# ── Optional Dependencies ────────────────────────────────────────────────
install_optional_deps() {
    if [ -z "$PKG_MGR" ]; then return; fi
    if ! _yes_no "  Install optional tools (ripgrep, ddgr, fzf, bat)?", "Y"; then
        return
    fi
    info "Installing optional tools..."
    case "$PKG_MGR" in
        apt) eval "sudo $PKG_INSTALL ripgrep fzf bat 2>/dev/null" || true
             pip3 install ddgr --quiet 2>/dev/null || true ;;
        dnf) eval "sudo $PKG_INSTALL ripgrep fzf bat 2>/dev/null" || true
             pip3 install ddgr --quiet 2>/dev/null || true ;;
        pacman) eval "sudo $PKG_INSTALL ripgrep fzf bat 2>/dev/null" || true
             pip3 install ddgr --quiet 2>/dev/null || true ;;
        brew) eval "$PKG_INSTALL ripgrep fzf bat ddgr 2>/dev/null" || true ;;
        *)    pip3 install ddgr --quiet 2>/dev/null || true ;;
    esac
    success "Optional tools installed"
}

# ── Playwright / Browser Installation ─────────────────────────────────────
install_playwright_browsers() {
    local venv_dir="$1"
    local venv_python="$venv_dir/bin/python"

    if [ ! -x "$venv_python" ]; then
        warn "No Python in venv, skipping browser install"
        return 1
    fi

    info "Installing Playwright Python package..."
    "$venv_python" -m pip install 'playwright>=1.40' --quiet 2>/dev/null || \
    "$venv_python" -m pip install 'playwright>=1.40'

    if ! "$venv_python" -c "import playwright" 2>/dev/null; then
        warn "Playwright pip install failed"
        return 1
    fi
    success "Playwright installed"

    local browser="chromium"

    if [ "$IS_TERMUX" = "yes" ]; then
        info "Installing system Chromium for Termux/Android..."
        pkg update -y 2>/dev/null || true
        pkg install -y x11-repo tur-repo 2>/dev/null || true
        if pkg install -y chromium 2>/dev/null; then
            success "Termux Chromium installed"
            # Verify it can be found
            local chrome_path="${PREFIX}/bin/chromium"
            if [ -x "$chrome_path" ]; then
                info "Chromium binary at $chrome_path"
                # Set env var so Playwright finds it
                export PLAYWRIGHT_CHROMIUM_EXECUTABLE="$chrome_path"
            fi
        else
            warn "Termux Chromium not available, falling back to Firefox..."
            browser="firefox"
        fi
    fi

    info "Installing $browser browser via Playwright..."
    case "$PLATFORM" in
        android)
            if [ "$browser" = "chromium" ] && [ -n "${PLAYWRIGHT_CHROMIUM_EXECUTABLE:-}" ]; then
                info "Using system Chromium on Termux (no Playwright download needed)"
            else
                "$venv_python" -m playwright install firefox 2>/dev/null || \
                warn "Firefox install failed; browser may not work"
            fi
            ;;
        linux|wsl)
            case "$ARCH_LABEL" in
                ARM64|ARMv7|aarch64)
                    "$venv_python" -m playwright install chromium 2>/dev/null || \
                    "$venv_python" -m playwright install firefox 2>/dev/null || \
                    warn "No Playwright browser could be installed for ARM Linux"
                    ;;
                *)
                    "$venv_python" -m playwright install chromium 2>/dev/null || \
                    warn "Chromium install failed; run: python -m playwright install chromium"
                    ;;
            esac
            ;;
        macos)
            "$venv_python" -m playwright install chromium 2>/dev/null || \
            "$venv_python" -m playwright install firefox 2>/dev/null || \
            warn "Playwright browser install failed"
            ;;
        *)
            warn "Unknown platform, trying chromium..."
            "$venv_python" -m playwright install chromium 2>/dev/null || true
            ;;
    esac

    # Quick verification
    if "$venv_python" -c "
import os, sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        kwargs = {'headless': True, 'args': ['--no-sandbox', '--disable-dev-shm-usage']}
        if os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'):
            kwargs['executable_path'] = os.environ['PLAYWRIGHT_CHROMIUM_EXECUTABLE']
        b = p.chromium.launch(**kwargs)
        b.close()
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
" 2>/dev/null | grep -q OK; then
        success "$browser browser works on this platform!"
    else
        warn "Browser verification failed. Trying Firefox fallback..."
        if "$venv_python" -m playwright install firefox 2>/dev/null; then
            "$venv_python" -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.firefox.launch(headless=True, args=['--no-sandbox'])
    b.close()
print('OK')
" 2>/dev/null | grep -q OK && success "Firefox browser works!" || warn "No working browser found"
        fi
    fi
}

_yes_no() {
    local prompt="$1"
    local default="${2:-Y}"
    local ans
    if [ "$default" = "Y" ]; then
        read -r -p "  $prompt [Y/n] " ans
        case "$ans" in n|N|no|NO) return 1 ;; *) return 0 ;; esac
    else
        read -r -p "  $prompt [y/N] " ans
        case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
    fi
}

# ── Platform Detection ──────────────────────────────────────────────────
detect_platform() {
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    # Termux / Android detection
    if [ -n "${PREFIX:-}" ] && [ -d "${PREFIX:-}" ]; then
        IS_TERMUX="yes"
        PLATFORM="android"
        info "Detected: Android/Termux ($ARCH_LABEL)"
        return
    fi
    if [ "$(uname -o 2>/dev/null)" = "Android" ] 2>/dev/null; then
        IS_TERMUX="yes"
        PLATFORM="android"
        info "Detected: Android ($ARCH_LABEL)"
        return
    fi

    case "$OS" in
        Linux*)
            if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then
                PLATFORM="wsl"
                info "Detected: WSL ($ARCH_LABEL)"
            else
                PLATFORM="linux"
                info "Detected: Linux ($ARCH_LABEL)"
            fi
            ;;
        Darwin*)
            PLATFORM="macos"
            info "Detected: macOS ($ARCH_LABEL)"
            ;;
        *)
            error "Unsupported platform: $OS"
            echo "  Use install.ps1 for Windows, or WSL for Windows Subsystem for Linux."
            exit 1
            ;;
    esac
}

# ── Python Detection ────────────────────────────────────────────────────
find_python() {
    # Try python3.14, 3.13, 3.12, 3.11 in order
    for ver in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$ver" &>/dev/null; then
            PYTHON_CMD="$ver"
            PYTHON_VERSION=$("$ver" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            PYTHON_PATH="$(command -v "$ver")"
            break
        fi
    done

    if [ -z "${PYTHON_CMD:-}" ]; then
        error "Python 3.11+ not found."
        echo ""
        echo "  Install Python first:"
        echo "    Linux:  sudo apt install python3 python3-venv  (or your package manager)"
        echo "    macOS:  brew install python3"
        echo "    WSL:    sudo apt install python3 python3-venv"
        exit 1
    fi

    MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]); then
        error "Python 3.11+ required, found $PYTHON_VERSION"
        exit 1
    fi

    success "Python $PYTHON_VERSION found at $PYTHON_PATH"
}

# ── Install Directory ──────────────────────────────────────────────────
resolve_install_dir() {
    if [ -n "$INSTALL_DIR" ]; then
        INSTALL_DIR="$(mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR" && pwd)"
        return
    fi

    # If running from a git clone or extracted directory with pyproject.toml
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
        if [ -w "$SCRIPT_DIR" ]; then
            INSTALL_DIR="$SCRIPT_DIR"
            info "Installing from source: $INSTALL_DIR"
            return
        else
            warn "Source dir not writable ($SCRIPT_DIR), installing to home instead."
        fi
    fi

    # Default: ~/.local/share/delux
    INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/delux"
    info "Default install: $INSTALL_DIR"
}

# ── Shell Detection ────────────────────────────────────────────────────
detect_shell() {
    CURRENT_SHELL="$(basename "${SHELL:-/bin/bash}")"
    case "$CURRENT_SHELL" in
        fish)   DETECTED_SHELL="fish" ;;
        zsh)    DETECTED_SHELL="zsh" ;;
        bash*)  DETECTED_SHELL="bash" ;;
        *)      DETECTED_SHELL="bash" ;;
    esac
    info "Current shell: $DETECTED_SHELL"
}

# ── Installation Methods ────────────────────────────────────────────────
_ensure_writable() {
    local dir="$1"
    if [ -w "$dir" ]; then
        return 0
    fi
    warn "Directory $dir is not writable. Fixing permissions..."
    if command -v sudo &>/dev/null; then
        sudo chown -R "$(whoami)" "$dir" 2>/dev/null && success "Permissions fixed" && return 0
    fi
    error "Cannot write to $dir. Try: sudo chown -R $(whoami) $dir"
    return 1
}

install_from_source() {
    local src_dir="$1"
    local venv_dir="$2"

    _ensure_writable "$src_dir" || return 1
    _ensure_writable "$(dirname "$venv_dir")" || return 1
    mkdir -p "$venv_dir" 2>/dev/null

    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$venv_dir" --system-site-packages 2>/dev/null || \
    "$PYTHON_CMD" -m venv "$venv_dir"

    local venv_python="$venv_dir/bin/python"
    local venv_pip="$venv_dir/bin/pip"

    # Fix egg-info if it exists and is unwritable
    local egg_info="$src_dir/delux_agent.egg-info"
    if [ -d "$egg_info" ] && [ ! -w "$egg_info" ]; then
        _ensure_writable "$egg_info" || true
    fi

    info "Installing Delux Agent..."
    "$venv_python" -m pip install --upgrade pip --quiet 2>/dev/null || true
    "$venv_pip" install -e "$src_dir" --quiet 2>/dev/null || \
    "$venv_pip" install -e "$src_dir" --no-build-isolation --quiet 2>/dev/null || {
        local egg_tmp="$src_dir/delux_agent.egg-info"
        if [ -d "$egg_tmp" ] && [ ! -w "$egg_tmp" ]; then
            warn "egg-info not writable, trying to fix..."
            _ensure_writable "$egg_tmp" && \
            "$venv_pip" install -e "$src_dir" --no-build-isolation --quiet
        fi
    }
    "$venv_pip" install pandas pyarrow --quiet 2>/dev/null || true

    if [ -x "$venv_dir/bin/delux" ]; then
        success "Installed in $venv_dir"
    else
        error "Installation failed. Check permissions."
        return 1
    fi
}

install_from_pypi() {
    local venv_dir="$1"

    info "Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$venv_dir" --system-site-packages 2>/dev/null || \
    "$PYTHON_CMD" -m venv "$venv_dir"

    local venv_python="$venv_dir/bin/python"
    local venv_pip="$venv_dir/bin/pip"

    info "Installing delux-agent from PyPI..."
    "$venv_python" -m pip install --upgrade pip --quiet 2>/dev/null
    "$venv_pip" install delux-agent --quiet 2>/dev/null || \
    "$venv_pip" install delux-agent

    success "Installed in $venv_dir"
}

# ── Shell Integration ──────────────────────────────────────────────────
setup_shell_integration() {
    local venv_bin="$1/bin"
    local src_dir="$2"
    local delux_cmd="$venv_bin/delux"

    if [ ! -x "$delux_cmd" ]; then
        warn "delux binary not found at $delux_cmd"
        return
    fi

    case "$DETECTED_SHELL" in
        fish)
            setup_fish "$venv_bin" "$src_dir"
            ;;
        zsh)
            setup_zsh "$venv_bin" "$src_dir"
            ;;
        bash)
            setup_bash "$venv_bin" "$src_dir"
            ;;
    esac
}

setup_fish() {
    local venv_bin="$1"
    local src_dir="$2"
    local fish_func_dir=""

    # Find fish functions directory
    if [ -d "$HOME/.config/fish/functions" ]; then
        fish_func_dir="$HOME/.config/fish/functions"
    elif [ -d "$HOME/.local/share/fish/functions" ]; then
        fish_func_dir="$HOME/.local/share/fish/functions"
    else
        mkdir -p "$HOME/.config/fish/functions"
        fish_func_dir="$HOME/.config/fish/functions"
    fi

    cat > "$fish_func_dir/delux.fish" <<'FISH'
function delux --description "Run Delux shell AI agent"
    set -l venv_dir "$DELUX_VENV"
    if test -z "$venv_dir"
        set -l script_dir (dirname (status --current-filename))
        # Try to find .venv in common locations
        for loc in "$script_dir/.venv" "$HOME/.local/share/delux/.venv"
            if test -d "$loc"
                set venv_dir "$loc"
                break
            end
        end
    end
    if test -n "$venv_dir" -a -x "$venv_dir/bin/delux"
        command "$venv_dir/bin/delux" $argv
    else if command -v delux &>/dev/null
        command delux $argv
    else
        echo "Delux not found. Run install.sh first." >&2
        return 1
    end
end
FISH

    # Replace $DELUX_VENV placeholder with actual path
    sed -i "s|\$DELUX_VENV|$INSTALL_DIR/.venv|g" "$fish_func_dir/delux.fish" 2>/dev/null || \
    sed -i '' "s|\$DELUX_VENV|$INSTALL_DIR/.venv|g" "$fish_func_dir/delux.fish" 2>/dev/null || true

    success "Fish integration: $fish_func_dir/delux.fish"
    echo -e "  ${DIM}Run 'source ~/.config/fish/config.fish' or restart fish${RESET}"

    # Install fish completions
    local fish_comp_dir="$HOME/.config/fish/completions"
    mkdir -p "$fish_comp_dir"
    if [ -f "$src_dir/completions/delux.fish" ]; then
        cp "$src_dir/completions/delux.fish" "$fish_comp_dir/"
        success "Fish completions installed"
    fi
}

setup_zsh() {
    local venv_bin="$1"
    local src_dir="$2"
    local zshrc="$HOME/.zshrc"

    # Check if already configured
    if grep -q "# Delux Agent" "$zshrc" 2>/dev/null; then
        warn "Zsh integration already exists in $zshrc"
        return
    fi

    cat >> "$zshrc" <<ZSH

# Delux Agent
alias delux="$venv_bin/delux"
ZSH

    success "Zsh integration: added alias to $zshrc"
    echo -e "  ${DIM}Run 'source ~/.zshrc' or restart terminal${RESET}"

    # Install zsh completions
    local zsh_comp_dir="$HOME/.zsh/completion"
    local site_func="/usr/local/share/zsh/site-functions"
    mkdir -p "$zsh_comp_dir"
    if [ -f "$src_dir/completions/_delux" ]; then
        cp "$src_dir/completions/_delux" "$zsh_comp_dir/_delux"
        # Source in .zshrc if not already
        if ! grep -q "fpath.*zsh/completion" "$zshrc" 2>/dev/null; then
            echo "fpath=(~/.zsh/completion \$fpath)" >> "$zshrc"
        fi
        success "Zsh completions installed"
    fi
}

setup_bash() {
    local venv_bin="$1"
    local src_dir="$2"
    local bashrc="$HOME/.bashrc"

    # Check if already configured
    if grep -q "# Delux Agent" "$bashrc" 2>/dev/null; then
        warn "Bash integration already exists in $bashrc"
        return
    fi

    cat >> "$bashrc" <<BASH

# Delux Agent
alias delux="$venv_bin/delux"
BASH

    success "Bash integration: added alias to $bashrc"
    echo -e "  ${DIM}Run 'source ~/.bashrc' or restart terminal${RESET}"

    # Install bash completions
    local bash_comp_dir="/usr/share/bash-completion/completions"
    local user_comp_dir="$HOME/.bash_completion.d"
    if [ -d "$bash_comp_dir" ] && [ -w "$bash_comp_dir" ]; then
        if [ -f "$src_dir/completions/delux.bash" ]; then
            sudo cp "$src_dir/completions/delux.bash" "$bash_comp_dir/delux" 2>/dev/null || \
            cp "$src_dir/completions/delux.bash" "$bash_comp_dir/delux" 2>/dev/null || true
            success "Bash completions installed"
        fi
    elif [ -f "$src_dir/completions/delux.bash" ]; then
        mkdir -p "$user_comp_dir"
        cp "$src_dir/completions/delux.bash" "$user_comp_dir/delux"
        # Source it in .bashrc if not already
        if ! grep -q "delux.bash" "$HOME/.bashrc" 2>/dev/null; then
            echo "[ -f ~/.bash_completion.d/delux ] && source ~/.bash_completion.d/delux" >> "$HOME/.bashrc"
        fi
        success "Bash completions installed"
    fi
}

# ── Usage ───────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
${BOLD}Delux Agent Installer${RESET}

Usage: $0 [options]

Options:
  --dir DIR         Install directory (default: source dir or ~/.local/share/delux)
  --system          Install system-wide (requires sudo)
  --no-shell        Skip shell integration
  --no-setup        Skip interactive setup wizard
  --browser         Install Playwright + browser (Chromium/Firefox) for web automation
  --help            Show this help

Examples:
  # Install from git clone or extracted tarball
  bash install.sh

  # Install to custom directory
  bash install.sh --dir ~/delux

  # Install without shell integration
  bash install.sh --no-shell

  # One-line install from the web
  curl -fsSL https://raw.githubusercontent.com/anomalyco/delux-agent/main/install.sh | bash
EOF
    exit 0
}

# ── Parse Arguments ────────────────────────────────────────────────────
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --dir)      INSTALL_DIR="$2"; shift 2 ;;
        --system)   INSTALL_MODE="system"; shift ;;
        --no-shell) SKIP_SHELL="yes"; shift ;;
        --no-setup) RUN_SETUP="no"; shift ;;
        --browser)  INSTALL_BROWSER="yes"; shift ;;
        --help|-h)  usage ;;
            *)          error "Unknown option: $1"; usage ;;
        esac
    done
}

# ── Main ────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    echo ""
    echo -e "  ${BOLD}${CYAN}◆${RESET} ${BOLD}Delux Agent Installer${RESET}"
    echo -e "  ${DIM}Shell-first AI assistant — cross-platform${RESET}"
    echo ""

    detect_architecture
    detect_platform
    find_python
    detect_package_manager
    resolve_install_dir
    detect_shell

    # ── Fix permissions on known Delux dirs (in case of previous sudo install) ──
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ "$INSTALL_DIR" != "$SCRIPT_DIR" ]; then
        _ensure_writable "$INSTALL_DIR" 2>/dev/null || true
    fi
    if [ -d "$INSTALL_DIR/.venv" ] && [ ! -w "$INSTALL_DIR/.venv" ]; then
        _ensure_writable "$INSTALL_DIR/.venv/" 2>/dev/null || true
    fi
    if [ -d "$HOME/.delux" ] && [ ! -w "$HOME/.delux" ]; then
        _ensure_writable "$HOME/.delux" 2>/dev/null || true
    fi

    # ── System dependencies ──
    if [ "${SKIP_DEPS:-no}" != "yes" ] && [ -n "$PKG_MGR" ] && [ "$IS_TERMUX" != "yes" ]; then
        echo ""
        install_system_deps
        install_optional_deps
    fi

    # ── Termux system deps (using pkg) ──
    if [ "$IS_TERMUX" = "yes" ]; then
        echo ""
        info "Termux detected — installing Python deps via pkg..."
        pkg update -y 2>/dev/null || true
        pkg install -y python ninja 2>/dev/null || true
    fi

    echo ""

    # Determine installation method
    if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
        # Install from source even if INSTALL_DIR != SCRIPT_DIR (not-writable case)
        install_from_source "$SCRIPT_DIR" "$INSTALL_DIR/.venv"
        VENV_DIR="$INSTALL_DIR/.venv"
        INSTALL_DIR="$SCRIPT_DIR"
    elif [ -f "$INSTALL_DIR/pyproject.toml" ]; then
        install_from_source "$INSTALL_DIR" "$INSTALL_DIR/.venv"
        VENV_DIR="$INSTALL_DIR/.venv"
    else
        mkdir -p "$INSTALL_DIR"
        install_from_pypi "$INSTALL_DIR"
        VENV_DIR="$INSTALL_DIR/.venv"
    fi

    # ── Playwright / Browser installation ──
    if [ "$INSTALL_BROWSER" = "yes" ]; then
        echo ""
        install_playwright_browsers "$VENV_DIR"
    fi

    # Shell integration
    if [ "$SKIP_SHELL" != "yes" ]; then
        echo ""
        setup_shell_integration "$VENV_DIR" "$INSTALL_DIR"
    fi

    # ── Auto-setup (interactive) ──
    if [ "$RUN_SETUP" = "auto" ] && [ -t 0 ]; then
        echo ""
        echo -e "  ${BOLD}${GREEN}Installation complete!${RESET}"
        echo ""
        if _yes_no "  Run the interactive setup wizard now?" "Y"; then
            echo ""
            "$VENV_DIR/bin/delux" setup
            echo ""
            if _yes_no "  Install default skills?" "Y"; then
                "$VENV_DIR/bin/delux" install-skills
            fi
            if [ "$INSTALL_BROWSER" != "yes" ]; then
                if _yes_no "  Install browser automation (Playwright + Chromium for web tasks)?" "Y"; then
                    install_playwright_browsers "$VENV_DIR"
                fi
            fi
            SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
            if [ -d "$SCRIPT_DIR/dataset_hermes" ]; then
                if _yes_no "  Import agent trajectory dataset into local RAG? (requires pandas)" "Y"; then
                    info "Installing pandas+pyarrow for dataset import..."
                    "$VENV_DIR/bin/pip" install pandas pyarrow --quiet 2>/dev/null || true
                    "$VENV_DIR/bin/python3" -c "
from delux_agent.dataset_rag import DatasetRAG
from pathlib import Path
ds = DatasetRAG(Path.home() / '.delux')
src_path = Path('$SCRIPT_DIR')
paths = [
    (src_path / 'dataset_hermes/data/kimi/train.parquet', ds.SOURCE_HERMES_KIMI),
    (src_path / 'dataset_hermes/data/glm-5.1/train.parquet', ds.SOURCE_HERMES_GLM),
    (src_path / 'dataset_multiturn/data/train-00000-of-00001.parquet', ds.SOURCE_MULTITURN),
]
total = 0
for p, src in paths:
    if p.exists():
        n = ds.import_hermes_parquet(str(p), src)
        total += n
        print(f'  Imported {n} from {p.name}')
print(f'  Total: {total} entries in dataset RAG')
                    " 2>&1 || echo "  (dataset import skipped)"
                fi
            elif [ -f "$SCRIPT_DIR/rag-raw/dataset-rag.jsonl.gz" ]; then
                if _yes_no "  Install pre-built agent trajectory RAG?" "Y"; then
                    DEST="$HOME/.delux/dataset-rag"
                    mkdir -p "$DEST"
                    cp "$SCRIPT_DIR/rag-raw/dataset-rag.jsonl.gz" "$DEST/entries.jsonl.gz"
                    echo '{"prebuilt":1}' > "$DEST/manifest.json"
                    echo "  Installed pre-built RAG"
                fi
            else
                info "Dataset files not found in $SCRIPT_DIR, skipping RAG import."
            fi
        fi
    fi

    # ── Final message ──
    echo ""
    echo -e "  ${BOLD}${GREEN}Delux is ready!${RESET}"
    echo ""
    echo -e "  ${CYAN}Quick start:${RESET}"
    echo -e "    ${BOLD}delux${RESET}                Open interactive IDE"
    echo -e "    ${BOLD}delux \"task\"${RESET}        Run a one-shot prompt"
    echo -e "    ${BOLD}delux setup${RESET}          Reconfigure settings"
    echo ""
    echo -e "  ${DIM}Direct: $VENV_DIR/bin/delux${RESET}"
    echo ""
}

main "$@"
