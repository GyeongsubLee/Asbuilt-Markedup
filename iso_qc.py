"""Entry point (also used by PyInstaller): python iso_qc.py [--base FOLDER]"""
import multiprocessing
import sys

from isoqc.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
