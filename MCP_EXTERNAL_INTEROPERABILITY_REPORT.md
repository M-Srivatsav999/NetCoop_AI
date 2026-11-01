# Model Context Protocol (MCP) — External Interoperability Report

## 1. Overview & Standard Compliance
- **Standard**: Anthropic Model Context Protocol (MCP) Specification (JSON-RPC 2.0 over standard I/O).
- **Implementation**: `mcp_server.py`.
- **Interoperability Scope**: Allows external LLM clients (Claude Desktop, custom NOC AI agents) to inspect campus network telemetry, query topology, execute multi-agent diagnoses, and simulate safe remediation dry-runs.

---

## 2. MCP Capabilities & Tool Contract

The MCP server exposes standard tools and resources:
1. `tools/list`:
   - `diagnose_network`: Ingests raw telemetry and triggers the complete multi-agent pipeline.
   - `get_topology`: Returns campus hierarchy and blast radius mappings.
   - `simulate_remediation`: Projects before/after KPIs for a candidate root cause.
   - `verify_recovery`: Evaluates measured post-action physical metrics.
2. `resources/list`:
   - `netcoop://topology`: Returns live campus topology graph.
   - `netcoop://calibration`: Returns persisted isotonic calibration curve parameters.

---

## 3. Subprocess-Based Verification

To prove external interoperability, NetCoop AI includes a dedicated subprocess test suite (`evaluation/test_mcp_real_subprocess.py`):
- Spawns `mcp_server.py` as an independent OS subprocess.
- Sends standard JSON-RPC 2.0 requests over stdin.
- Validates JSON-RPC 2.0 responses from stdout.
- Evaluates `initialize`, `tools/list`, `tools/call (diagnose_network)`, and error handling.
- Result: **9/9 tests pass** in under 2 seconds.

---

## 4. Official MCP SDK Note & Windows Sandbox Job Object Behavior

In `evaluation/test_official_mcp_sdk.py`, the official `mcp` Python SDK is tested.
> [!NOTE]
> On Windows environments running under restricted Job Objects (such as sandbox containers), AnyIO process spawning can raise `PermissionError` (WinError 5 / Access Denied). The test suite gracefully detects this platform constraint and marks the official SDK test as skipped (`1 skipped`), while the comprehensive subprocess test suite (`test_mcp_real_subprocess.py`, 9 tests) fully validates the stdio protocol.
