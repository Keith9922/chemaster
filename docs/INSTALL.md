# Installing ChemMaster

ChemMaster ships as a Python CLI plus a set of optional chemistry-engine
dependencies. There are three install paths depending on how heavy you
want the install to be.

---

## TL;DR — one line

```bash
curl -sSL https://raw.githubusercontent.com/Keith9922/chemaster/main/scripts/install.sh | bash
```

This:
- Verifies Python ≥ 3.11
- Bootstraps `pipx` if not present
- Installs `chemaster` into its own isolated venv (no conflicts with your
  project deps)
- Detects whether psi4 / xtb / Gaussian / ORCA is on `$PATH` and prints
  a conda hint if none is found

After it finishes, `chemaster --check-engines` will tell you exactly
what is and isn't reachable.

---

## Option 1 — pipx (recommended)

Use this if you want the CLI globally available but isolated.

```bash
# 0. (One-time) Make sure pipx itself is installed
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# 1. Install chemaster
pipx install chemaster

# 2. Try it
chemaster --version
chemaster --check-engines
chemaster run "compute H2O energy with HF/sto-3g"
```

To upgrade later: `pipx upgrade chemaster`.

---

## Option 2 — uv / uvx (ephemeral, fastest)

If you already use [`uv`](https://github.com/astral-sh/uv):

```bash
# Ephemeral — run without installing
uvx chemaster --version
uvx chemaster run "compute H2O energy"

# Or persistent install
uv tool install chemaster
```

Or via the one-liner with `--use-uv`:

```bash
curl -sSL https://raw.githubusercontent.com/Keith9922/chemaster/main/scripts/install.sh | bash -s -- --use-uv
```

---

## Option 3 — conda / mamba (chemistry-stack users)

If you already manage scientific Python with conda, you probably want
psi4 in the same env. `pipx`/`uvx` will not give you psi4 because psi4
is conda-only (no PyPI wheel).

```bash
# 1. Create a chemistry env
mamba create -n chemmaster python=3.11 -y
mamba activate chemmaster

# 2. Install psi4 + xtb from conda-forge
mamba install -c psi4 -c conda-forge psi4 xtb -y

# 3. Install chemaster on top via pip
pip install chemaster

# 4. Verify
chemaster --check-engines
```

---

## Chemistry engines — install matrix

| Engine     | Install command                                  | License           | Notes                                  |
|------------|--------------------------------------------------|-------------------|----------------------------------------|
| **psi4**   | `mamba install -c psi4 psi4`                     | Open source       | Recommended default backend            |
| **xtb**    | `mamba install -c conda-forge xtb`               | Open source       | Semi-empirical, very fast              |
| **PySCF**  | `pip install pyscf` (already a base dep)         | Open source       | X2C SOC reference                      |
| **Gaussian** | Vendor installer; ensure `g16` on `$PATH`      | Commercial        | Required for production TADF work      |
| **ORCA**   | Vendor installer; ensure `orca` on `$PATH`       | Free for academic | DLPNO-CCSD(T), CASSCF                  |
| **BDF**    | Free for academic; ensure `bdf` on `$PATH`       | Free for academic | Best-in-class SOC                      |
| **MOMAP**  | Vendor installer; ensure `momap` on `$PATH`      | Commercial        | TVCF rates, vibration-resolved spectra |

ChemMaster degrades gracefully — only the tools that need a missing
engine become unavailable. The agent kernel, KB, unit conversion, and
the MCP-server layer all work without any engine installed.

---

## Verifying the install

```bash
# Version
chemaster --version

# What engines are reachable
chemaster --check-engines

# Full tool / MCP list
chemaster tools list
chemaster mcps list

# 30-second smoke test (uses MockLLM, no API key needed)
chemaster run "list available skills" --llm-provider mock --no-confirm
```

Expected output of `--check-engines` on a "Option 1 (pipx, no conda)"
machine — only PySCF (a base Python dep) is available:

```
✓ pyscf      → /Users/you/.local/share/pipx/.../bin/python -m pyscf
✗ psi4       → not found       (install: mamba install -c psi4 psi4)
✗ xtb        → not found       (install: mamba install -c conda-forge xtb)
✗ gaussian   → not found       (commercial — request from vendor)
✗ orca       → not found       (free academic — request from vendor)
✗ bdf        → not found       (free academic — request from vendor)
✗ momap      → not found       (commercial — request from vendor)
```

---

## Uninstall

```bash
pipx uninstall chemaster
# or for uv users:
uv tool uninstall chemaster
```

User config / cache (skills, prefs, runs/) lives in
`~/.chemaster/` — remove it manually if you also want to scrub state.

---

## Troubleshooting

**`chemaster: command not found` after install** — pipx couldn't add its
bin directory to your PATH. Run `pipx ensurepath` and open a new shell.

**`ModuleNotFoundError: No module named 'psi4'` when running a tool that
needs psi4** — pipx doesn't see your conda env. Either: (a) use Option
3 (conda + pip install chemaster), or (b) start the agent from a shell
where psi4 is on PATH.

**Slow first run** — Python + pipx caches are cold. Subsequent runs are
≪ 200 ms for typed-string tasks (KB lookup / unit conversion / list
skills). Cf. §4.4.3 of the thesis for scalability numbers.

**On WSL2** — psi4 wheels are not currently published for `aarch64`. If
you are on an ARM-based Windows machine (Snapdragon X / Surface Pro
2024+), use Option 1 (pipx, no engine) plus run the heavy chemistry on
a remote x86 server via the `hpc_slurm` adapter.
