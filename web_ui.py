"""NetCoop AI — Full Interactive Web NOC Dashboard.

Launches the unified FastAPI web server providing the professional 8-section NOC interface
for live incident diagnosis, topology visualization, synthetic generation,
remediation simulation, and Page 5 JSON report export.
"""

from __future__ import annotations

import sys
import uvicorn
from web.server import app


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    sys.stderr.write(f"\n=======================================================\n")
    sys.stderr.write(f" NETCOOP AI — INTERACTIVE NOC COMMAND CENTER (v5.2)\n")
    sys.stderr.write(f" Access UI in browser at: http://{host}:{port}\n")
    sys.stderr.write(f" Unified Backend: web.server:app (8 NOC Sections Active)\n")
    sys.stderr.write(f"=======================================================\n\n")
    sys.stderr.flush()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
