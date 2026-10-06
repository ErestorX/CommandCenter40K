"""Start the Command Center 40K app:  python main.py   (command line tools: python -m command_center -h)"""
import multiprocessing

from command_center.ui.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()        # packaged app: a worker process of the Optimizer, not a second app
    main()
