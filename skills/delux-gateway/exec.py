#!/usr/bin/env python3
"""Delux Gateway — Telegram to Delux Agent bridge."""

import sys
import os

# Add the project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from delux_agent.gateway import run_gateway

if __name__ == "__main__":
    run_gateway()
