#!/usr/local/bin/python
"""
Vehicle Information System - Command Line Interface

This script provides a command-line interface to query vehicle information
from data.gov.il, either from local CSV files or via API.
"""

import sys
from vehicle_info.main import main

if __name__ == "__main__":
    main()