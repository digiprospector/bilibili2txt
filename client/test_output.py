#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from tqdm import tqdm
from pathlib import Path
import sys

# Add parent directories to path to import dp_logging
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))
from dp_logging import setup_logger

# Setup logger
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

def main():
    """
    A test script that prints 20 lines of text and then shows a tqdm progress bar.
    """
    logger.info("--- Starting to print 20 lines of text ---")
    for i in range(1, 21):
        logger.info(f"This is line number {i}")
        time.sleep(0.05)

    logger.info("--- Finished printing text, now starting tqdm progress bar ---")

    # Simulate a process with a progress bar
    for i in tqdm(range(100), desc="Processing items"):
        time.sleep(0.03)

    logger.info("--- TQDM progress bar finished ---")
    logger.info("Test script completed.")

if __name__ == "__main__":
    main()