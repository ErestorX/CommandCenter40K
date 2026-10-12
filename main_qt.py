"""Start the Command Center 40K app with its Qt front end, under way (docs/qt_migration.md):  python main_qt.py"""
import multiprocessing

from command_center.qt.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()        # packaged app: a worker process of the Optimizer, not a second app
    main()
