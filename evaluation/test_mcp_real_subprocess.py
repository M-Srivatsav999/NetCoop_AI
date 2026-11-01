"""Independent Subprocess MCP Interoperability Test for NetCoop AI.

Proves real external process interoperability by launching the MCP server in a separate
OS subprocess and communicating via standard JSON-RPC 2.0 stdio pipes:
1. Subprocess lifecycle management (launch, handshake, clean EOF shutdown).
2. Protocol initialization (initialize -> notifications/initialized).
3. Tool discovery (tools/list) returning standard schemas.
4. Diagnostic tool execution (diagnose_telemetry) over stdio.
5. Blast radius tool execution (get_blast_radius) over stdio.
6. Remediation simulation execution (simulate_remediation) over stdio.
7. Campus topology query (get_campus_topology) over stdio.
8. Parameter validation errors (JSON-RPC -32602).
9. Unsupported method errors (JSON-RPC -32601).
10. Malformed JSON parse error (JSON-RPC -32700).
11. Capture of structured protocol exchange logs.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SubprocessMCPClient:
    """External client that runs the MCP server as an independent child subprocess."""

    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 1
        self.exchange_logs: List[Dict[str, Any]] = []

    def start(self) -> None:
        """Launch the MCP server subprocess."""
        cmd = [sys.executable, str(PROJECT_ROOT / "mcp_server.py")]
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(PROJECT_ROOT)
        )

    def send_raw(self, line: str) -> Optional[str]:
        """Send a single line to server stdin and read single line from server stdout."""
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Subprocess is not running")

        assert self.process.stdin is not None
        assert self.process.stdout is not None

        self.process.stdin.write(line.strip() + "\n")
        self.process.stdin.flush()

        resp_line = self.process.stdout.readline()
        if not resp_line:
            return None
        return resp_line.strip()

    def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send a notification (no id) - per JSON-RPC 2.0 no response expected."""
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        payload = json.dumps(msg)
        self.exchange_logs.append({"type": "NOTIFICATION_SENT", "payload": msg})

        assert self.process and self.process.stdin
        self.process.stdin.write(payload + "\n")
        self.process.stdin.flush()

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send standard JSON-RPC 2.0 request and await response."""
        req_id = self.request_id
        self.request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        raw_req = json.dumps(req)
        self.exchange_logs.append({"type": "REQUEST_SENT", "id": req_id, "method": method, "payload": req})

        raw_resp = self.send_raw(raw_req)
        assert raw_resp is not None, f"Server closed stdout without response for request id={req_id}"

        resp = json.loads(raw_resp)
        self.exchange_logs.append({"type": "RESPONSE_RECEIVED", "id": req_id, "payload": resp})
        return resp

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Call tool via tools/call and return (result_data, error_dict)."""
        resp = self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        if "error" in resp:
            return {}, resp["error"]

        content = resp["result"]["content"][0]["text"]
        return json.loads(content), None

    def close(self) -> int:
        """Close stdin and wait for graceful termination."""
        if self.process:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass
            try:
                ret = self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                ret = self.process.wait()
            return ret
        return 0


@pytest.fixture
def mcp_subprocess():
    """Fixture providing an active MCP subprocess client."""
    client = SubprocessMCPClient()
    client.start()
    yield client
    client.close()


def test_subprocess_mcp_handshake_and_lifecycle(mcp_subprocess):
    """Test standard MCP initialize handshake and notification handling."""
    client = mcp_subprocess

    # 1. Initialize
    init_resp = client.send_request("initialize", {
        "protocolVersion": "2024-11-05",
        "clientInfo": {"name": "test-subprocess-harness", "version": "1.0.0"}
    })
    assert init_resp["jsonrpc"] == "2.0"
    assert "result" in init_resp
    assert init_resp["result"]["protocolVersion"] == "2024-11-05"
    assert init_resp["result"]["serverInfo"]["name"] == "netcoop-ai-mcp"
    assert "tools" in init_resp["result"]["capabilities"]

    # 2. Initialized notification (no reply expected)
    client.send_notification("notifications/initialized")

    # 3. Ping
    ping_resp = client.send_request("ping")
    assert ping_resp["jsonrpc"] == "2.0"
    assert "result" in ping_resp


def test_subprocess_mcp_tool_discovery(mcp_subprocess):
    """Test discovering available diagnostic tools via tools/list."""
    client = mcp_subprocess
    resp = client.send_request("tools/list")
    assert resp["jsonrpc"] == "2.0"
    tools = resp["result"]["tools"]
    tool_map = {t["name"]: t for t in tools}

    assert "diagnose_telemetry" in tool_map
    assert "get_blast_radius" in tool_map
    assert "simulate_remediation" in tool_map
    assert "get_campus_topology" in tool_map

    # Check required schemas
    assert "telemetry" in tool_map["diagnose_telemetry"]["inputSchema"]["required"]
    assert "device_id" in tool_map["get_blast_radius"]["inputSchema"]["required"]
    assert "root_cause" in tool_map["simulate_remediation"]["inputSchema"]["required"]


def test_subprocess_mcp_diagnose_telemetry_tool(mcp_subprocess):
    """Test invoking diagnose_telemetry on external server process."""
    client = mcp_subprocess

    telemetry_payload = json.dumps([
        {
            "device_id": "IITBBS-SW-MHR",
            "timestamp": "2026-10-31T20:00:00Z",
            "status": "WARNING",
            "metrics": {
                "latency_ms": 190.0,
                "packet_loss_pct": 6.5,
                "queue_drops": 120,
                "interface_errors": 0
            }
        }
    ])

    data, err = client.call_tool("diagnose_telemetry", {
        "telemetry": telemetry_payload,
        "incident_id": "MCP-SUBPROC-001"
    })
    assert err is None
    assert data["diagnosed_root_cause"] == "LINK_CONGESTION"
    assert data["confidence"] >= 0.70
    assert data["report"]["incident_id"] == "MCP-SUBPROC-001"
    assert "IITBBS-SW-MHR" in data["report"]["affected_devices"]
    assert data["duration_ms"] > 0


def test_subprocess_mcp_blast_radius_and_topology_tools(mcp_subprocess):
    """Test blast radius and campus topology query via real subprocess."""
    client = mcp_subprocess

    # Blast radius
    br_data, br_err = client.call_tool("get_blast_radius", {"device_id": "IITBBS-SW-MHR"})
    assert br_err is None
    assert br_data["root_device_id"] == "IITBBS-SW-MHR"
    assert br_data["total_downstream_count"] >= 2
    assert "AP-MHR-W1" in br_data["downstream_device_ids"]

    # Campus topology
    topo_data, topo_err = client.call_tool("get_campus_topology", {})
    assert topo_err is None
    assert topo_data["total_nodes"] >= 5
    assert topo_data["root_core_switch"] in ("CORE-SW-01", "IITBBS-CORE-SW1")


def test_subprocess_mcp_simulate_remediation_tool(mcp_subprocess):
    """Test remediation simulation via real subprocess."""
    client = mcp_subprocess

    data, err = client.call_tool("simulate_remediation", {
        "root_cause": "HARDWARE_FAILURE",
        "affected_devices": ["IITBBS-SW-MHR"]
    })
    assert err is None
    assert data["suspected_root_cause"] == "HARDWARE_FAILURE"
    assert len(data["actions"]) >= 1
    assert data["actions"][0]["target_device"] == "IITBBS-SW-MHR"
    assert data["lifecycle_state"] == "SIMULATED"
    assert "dry-run" in data.get("dry_run_disclaimer", "").lower()


def test_subprocess_mcp_invalid_arguments_error(mcp_subprocess):
    """Test parameter validation error codes (-32602) from real subprocess."""
    client = mcp_subprocess

    # Missing required argument 'telemetry'
    resp = client.send_request("tools/call", {
        "name": "diagnose_telemetry",
        "arguments": {}
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Missing or invalid required argument" in resp["error"]["message"]

    # Missing required argument 'device_id' for get_blast_radius
    resp2 = client.send_request("tools/call", {
        "name": "get_blast_radius",
        "arguments": {}
    })
    assert "error" in resp2
    assert resp2["error"]["code"] == -32602

    # Missing required argument for simulate_remediation
    resp3 = client.send_request("tools/call", {
        "name": "simulate_remediation",
        "arguments": {"root_cause": "HARDWARE_FAILURE"}
    })
    assert "error" in resp3
    assert resp3["error"]["code"] == -32602


def test_subprocess_mcp_unsupported_method_and_malformed_json(mcp_subprocess):
    """Test unsupported method (-32601) and malformed JSON (-32700) over subprocess pipes."""
    client = mcp_subprocess

    # Unsupported method
    resp = client.send_request("non_existent_rpc_method")
    assert "error" in resp
    assert resp["error"]["code"] == -32601

    # Malformed JSON line
    raw_resp = client.send_raw("{malformed_json_without_quotes")
    assert raw_resp is not None
    resp_obj = json.loads(raw_resp)
    assert "error" in resp_obj
    assert resp_obj["error"]["code"] == -32700


def test_subprocess_mcp_clean_shutdown(mcp_subprocess):
    """Test clean subprocess termination on shutdown method and EOF."""
    client = mcp_subprocess

    resp = client.send_request("shutdown")
    assert resp["result"] is None

    # Closing stdin signals EOF to server loop
    ret = client.close()
    assert ret == 0, f"Expected clean exit code 0, got {ret}"


def test_subprocess_protocol_exchange_logging():
    """Verify detailed protocol exchange capture between external client and subprocess."""
    client = SubprocessMCPClient()
    client.start()
    try:
        client.send_request("initialize")
        client.send_request("tools/list")
        client.call_tool("get_blast_radius", {"device_id": "IITBBS-SW-MHR"})
        client.send_request("shutdown")
        client.close()

        # Verify exchange logs
        assert len(client.exchange_logs) >= 6
        sent_types = [entry["type"] for entry in client.exchange_logs]
        assert "REQUEST_SENT" in sent_types
        assert "RESPONSE_RECEIVED" in sent_types
    finally:
        client.close()
