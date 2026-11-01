"""Pytest Root Configuration and System Fixtures for NetCoop AI.

Provides autouse fixtures for:
1. Concurrency-safe durable SQLite nonce store cleansing to prevent stale state locks across tests.
2. Lingering background Uvicorn / Web UI server process termination on ports 8000, 8001, 8080.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent


def terminate_dangling_server_ports(ports=(8000, 8001, 8080)) -> None:
    """Forcefully terminate any dangling background server processes on standard test ports in <0.2s."""
    if sys.platform == "win32":
        try:
            out = subprocess.check_output("netstat -ano -n", shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in out.strip().splitlines():
                if "LISTENING" in line and any(f":{p}" in line for p in ports):
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pid = parts[-1]
                        if int(pid) != os.getpid() and int(pid) != 0:
                            subprocess.run(
                                f"taskkill /F /PID {pid}",
                                shell=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL
                            )
        except Exception:
            pass
    else:
        for port in ports:
            try:
                out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL)
                for pid in out.strip().splitlines():
                    if pid.isdigit() and int(pid) != os.getpid():
                        os.kill(int(pid), 9)
            except Exception:
                pass


@pytest.fixture(autouse=True)
def clean_sqlite_nonce_store():
    """Ensure clean durable SQLite nonce table state before and after each test suite."""
    try:
        from core.remediation import DurableNonceStore
        DurableNonceStore.reset_db()
    except Exception:
        pass

    yield

    try:
        from core.remediation import DurableNonceStore
        DurableNonceStore.reset_db()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def ensure_clean_server_environment():
    """Ensure no lingering background dashboard server/uvicorn processes exist before or after session."""
    terminate_dangling_server_ports()
    yield
    terminate_dangling_server_ports()
