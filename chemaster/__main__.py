"""Allow `python -m chemaster …` as an alternate entry to the CLI.

Equivalent to running the `chemaster` console script defined in
pyproject.toml.
"""

from chemaster.cli import main

if __name__ == "__main__":
    main()
