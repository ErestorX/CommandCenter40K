"""`python -m command_center ...` -> the command-line interface."""
from command_center.cli import main

if __name__ == "__main__":      # required: worker processes (sweeps) re-import this module on Windows
    main()
