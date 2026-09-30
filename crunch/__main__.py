"""`python -m crunch ...` -> the command-line interface."""
from crunch.cli import main

if __name__ == "__main__":      # required: worker processes (sweeps) re-import this module on Windows
    main()
