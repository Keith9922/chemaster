#!/usr/bin/env bash
# ChemMaster one-line installer.
#
# Bootstraps the ChemMaster CLI onto a fresh machine with one command:
#
#     curl -sSL https://raw.githubusercontent.com/Keith9922/chemaster/main/scripts/install.sh | bash
#
# What this script does (in order):
#
#   1. Verify Python ≥ 3.11 is available.
#   2. Bootstrap pipx if needed (preferred isolation for CLI tools).
#   3. pipx install chemaster (or upgrade if already installed).
#   4. Detect whether a chemistry engine (psi4 / Gaussian / xtb / ORCA) is
#      reachable on $PATH; if none, print a friendly conda hint.
#   5. Run `chemaster --check-engines` to print the final state.
#
# Why not just `pip install`?  Because chemaster is a CLI, not a library —
# pipx isolates it in its own virtualenv so it never conflicts with your
# project deps. (uv users can pass --use-uv to use `uvx` instead.)
#
# Supported platforms: macOS, Linux, WSL2. Windows users: install via
# `pipx install chemaster` from PowerShell directly; this script depends
# on bash and standard POSIX tools.

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Style helpers
# ──────────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
    BOLD="$(tput bold)"
    GREEN="$(tput setaf 2)"
    YELLOW="$(tput setaf 3)"
    RED="$(tput setaf 1)"
    DIM="$(tput dim)"
    RESET="$(tput sgr0)"
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; DIM=""; RESET=""
fi

info()  { printf "%s→%s %s\n" "$BOLD" "$RESET" "$1"; }
ok()    { printf "%s✓%s %s\n" "$GREEN" "$RESET" "$1"; }
warn()  { printf "%s⚠%s %s\n" "$YELLOW" "$RESET" "$1"; }
fail()  { printf "%s✗%s %s\n" "$RED" "$RESET" "$1" >&2; exit 1; }

# ──────────────────────────────────────────────────────────────────────────────
# 0. CLI flags
# ──────────────────────────────────────────────────────────────────────────────

USE_UV=0
EXTRAS=""        # e.g. "[tui,web]"
INSTALL_REF=""   # e.g. main, a-tag, or empty for the published wheel

while [[ $# -gt 0 ]]; do
    case "$1" in
        --use-uv) USE_UV=1; shift ;;
        --extras) EXTRAS="$2"; shift 2 ;;
        --from-git) INSTALL_REF="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
        *) fail "Unknown flag: $1" ;;
    esac
done

# ──────────────────────────────────────────────────────────────────────────────
# 1. Python version check
# ──────────────────────────────────────────────────────────────────────────────

info "Checking Python version…"
if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found. Install Python ≥ 3.11 first (https://python.org)."
fi
PY_MAJ=$(python3 -c 'import sys; print(sys.version_info[0])')
PY_MIN=$(python3 -c 'import sys; print(sys.version_info[1])')
if [[ "$PY_MAJ" -lt 3 || ( "$PY_MAJ" -eq 3 && "$PY_MIN" -lt 11 ) ]]; then
    fail "Python ≥ 3.11 required, found $PY_MAJ.$PY_MIN"
fi
ok "Python $PY_MAJ.$PY_MIN"

# ──────────────────────────────────────────────────────────────────────────────
# 2. pipx / uvx bootstrap
# ──────────────────────────────────────────────────────────────────────────────

if [[ "$USE_UV" -eq 1 ]]; then
    info "Using uv (uvx)…"
    if ! command -v uv >/dev/null 2>&1; then
        info "Installing uv…"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # uv installs to ~/.local/bin or ~/.cargo/bin — add to PATH for this session
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
    ok "uv $(uv --version)"
else
    info "Checking pipx…"
    if ! command -v pipx >/dev/null 2>&1; then
        info "pipx not found, installing via pip --user…"
        python3 -m pip install --user pipx --quiet
        python3 -m pipx ensurepath
        # Reload PATH for this session — covers the common "~/.local/bin" case.
        export PATH="$HOME/.local/bin:$PATH"
        if ! command -v pipx >/dev/null 2>&1; then
            fail "pipx installed but not on PATH. Open a new shell and re-run."
        fi
    fi
    ok "pipx $(pipx --version)"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 3. Install chemaster
# ──────────────────────────────────────────────────────────────────────────────

# Spec passed to pipx/uvx. EXTRAS like "[tui,web]" is appended to the package
# name. INSTALL_REF turns the source into a git clone.
#
# CHEMASTER_RELEASE_BASE_URL is honoured for users behind GitHub-blocking
# networks (mainland China typically). When set, the git-clone path swaps
# the github.com host for the mirror host. Example:
#
#     CHEMASTER_RELEASE_BASE_URL=https://gitee.com/Keith9922/chemaster \
#       curl -sSL .../install.sh | bash -s -- --from-git main
#
GH_HOST="${CHEMASTER_RELEASE_BASE_URL:-https://github.com/Keith9922/chemaster}"

if [[ -n "$INSTALL_REF" ]]; then
    SPEC="git+${GH_HOST}.git@${INSTALL_REF}"
    if [[ -n "$EXTRAS" ]]; then
        warn "extras + --from-git not supported by some package managers; ignoring extras"
    fi
else
    SPEC="chemaster${EXTRAS}"
fi

info "Installing $SPEC…"
if [[ "$USE_UV" -eq 1 ]]; then
    uv tool install "$SPEC" --force
else
    pipx install "$SPEC" --force
fi

if ! command -v chemaster >/dev/null 2>&1; then
    warn "chemaster command not yet on PATH; you may need: source ~/.bashrc"
    export PATH="$HOME/.local/bin:$PATH"
fi
ok "chemaster $(chemaster --version 2>/dev/null || echo '(version unknown)')"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Chemistry-engine detection
# ──────────────────────────────────────────────────────────────────────────────

info "Detecting chemistry engines on PATH…"

ENGINE_FOUND=0
for engine_cmd in psi4 g16 g09 xtb orca; do
    if command -v "$engine_cmd" >/dev/null 2>&1; then
        ENGINE_FOUND=1
        ok "  $engine_cmd  → $(command -v $engine_cmd)"
    fi
done

if [[ "$ENGINE_FOUND" -eq 0 ]]; then
    warn "No chemistry engine detected on PATH."
    printf "\n%s%s%s\n" "$DIM" "  ChemMaster's CLI and KB work out-of-the-box, but you need" "$RESET"
    printf "%s%s%s\n" "$DIM" "  at least one engine to run actual calculations:" "$RESET"
    printf "\n"
    printf "  %spsi4   (recommended, free, open-source):%s\n" "$BOLD" "$RESET"
    printf "    conda install -c psi4 psi4\n"
    printf "\n"
    printf "  %sxtb    (semi-empirical, very fast):%s\n" "$BOLD" "$RESET"
    printf "    conda install -c conda-forge xtb\n"
    printf "\n"
    printf "  %sGaussian / ORCA / BDF / MOMAP:%s\n" "$BOLD" "$RESET"
    printf "    install per vendor instructions, ensure binary is on \$PATH\n"
    printf "\n"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 5. Final state
# ──────────────────────────────────────────────────────────────────────────────

printf "\n"
info "Final environment check:"
chemaster --check-engines || true

printf "\n%sChemMaster is ready.%s\n" "$BOLD" "$RESET"
printf "  Try: %schemaster run \"compute H2O energy\"%s\n" "$BOLD" "$RESET"
printf "  Or:  %schemaster tui%s   (interactive)\n" "$BOLD" "$RESET"
printf "  Or:  %schemaster mcp-serve%s   (mount as MCP server in Claude Code)\n" "$BOLD" "$RESET"
