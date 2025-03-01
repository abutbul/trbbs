#!/usr/bin/env python
import asyncio
import logging
from telegram_bot.main import run

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logging.critical(f"Fatal error in main program: {e}")
        exit(1)