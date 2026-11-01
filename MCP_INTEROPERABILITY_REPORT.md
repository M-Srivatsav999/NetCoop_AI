# NetCoop AI — Model Context Protocol (MCP) Interoperability Report

## Executive Summary
NetCoop AI exposes its autonomous network fault diagnosis, downstream blast-radius analysis, campus topology, and remediation simulation capabilities to external AI agents via the **Model Context Protocol (MCP)** standard over JSON-RPC 2.0 stdio pipes.

This report documents **true external subprocess interoperability**, rigorously verifying that an independent client operating outside the server's Python runtime successfully connects, negotiates the protocol handshake, discovers tool definitions, executes diagnostic queries, and gracefully manages process termination.

---

## 1. Subprocess Architecture & Transport Protocol

```
+-----------------------------------------------------------+
|              External Third-Party Client Process          |
|                  (e.g., Cursor, Claude Desktop, SDK)      |
+-----------------------------------------------------------+
            | stdin (JSON-RPC requests)      ^ stdout (JSON-RPC responses)
            v                                |
+-----------------------------------------------------------+
|               NetCoop AI MCP Server Subprocess            |
|                  (`mcp_server.py` daemon)                 |
|                                                           |
|   +-------------------+             +-----------------+   |
|   | JSON-RPC Parser   |             | Tool Dispatcher |   |
|   | (Code -32700/-601)|             | (Code -32602)   |   |
|   +-------------------+             +-----------------+   |
|            |                                 |            |
|            v                                 v            |
|   +-------------------+             +-----------------+   |
|   | Diagnostic Core   |             | Topology Engine |   |
|   | & Orchestrator    |             | & Remediation   |   |
|   +-------------------+             +-----------------+   |
+-----------------------------------------------------------+
```

### Transport Specifications
- **Transport**: Standard I/O (stdin / stdout pipes)
- **Protocol**: JSON-RPC 2.0 Specification
- **Encoding**: UTF-8, newline-delimited JSON
- **Process Isolation**: Fully isolated OS subprocess (`subprocess.Popen`)

---

## 2. Protocol Lifecycle & Tool Discovery

### Phase 1: Protocol Handshake
1. Client issues `initialize` request:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "clientInfo": {"name": "external-client", "version": "1.0.0"}
  }
}
```
2. Server returns capabilities and protocol version:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "netcoop-ai-mcp", "version": "1.0.0"},
    "capabilities": {"tools": {}}
  }
}
```
3. Client dispatches `notifications/initialized` notification (no response required).

### Phase 2: Tool Discovery (`tools/list`)
The server dynamically advertises 4 production tools with strict JSON schema definitions:
1. `diagnose_telemetry`: Runs multi-agent telemetry normalization and arbitration.
2. `get_blast_radius`: Calculates downstream device dependencies and blast-radius depth.
3. `simulate_remediation`: Produces dry-run corrective engineering playbooks with KPI projections.
4. `get_campus_topology`: Returns the 5-tier campus network adjacency graph.

---

## 3. Real Execution Verification

The independent subprocess test suite (`evaluation/test_mcp_real_subprocess.py`) executes 9 automated test vectors:

| Test Vector | Target Verification | Result |
| :--- | :--- | :--- |
| `test_subprocess_mcp_handshake_and_lifecycle` | Protocol handshake, serverInfo, and notifications | **PASS** |
| `test_subprocess_mcp_tool_discovery` | Discovery of all 4 tools and valid input schemas | **PASS** |
| `test_subprocess_mcp_diagnose_telemetry_tool` | End-to-end diagnosis of raw campus telemetry payload | **PASS** |
| `test_subprocess_mcp_blast_radius_and_topology_tools` | Blast-radius calculation on core/distribution switches | **PASS** |
| `test_subprocess_mcp_simulate_remediation_tool` | Corrective dry-run playbook generation | **PASS** |
| `test_subprocess_mcp_invalid_arguments_error` | Missing argument validation returns JSON-RPC `-32602` | **PASS** |
| `test_subprocess_mcp_unsupported_method_and_malformed_json` | Unknown methods return `-32601`, malformed JSON returns `-32700` | **PASS** |
| `test_subprocess_mcp_clean_shutdown` | `shutdown` method followed by clean exit code `0` on EOF | **PASS** |
| `test_subprocess_protocol_exchange_logging` | Audit trail of complete request/response log exchanges | **PASS** |

---

## 4. Error Handling Compliance

The server strictly complies with JSON-RPC 2.0 specification error codes:
- **Parse Error (`-32700`)**: Triggered when client sends invalid or unparseable JSON text.
- **Method Not Found (`-32601`)**: Triggered when client invokes an unregistered RPC method.
- **Invalid Params (`-32602`)**: Triggered when required parameters (`telemetry`, `device_id`, `root_cause`, `affected_devices`) are missing or of incorrect types.
- **Internal Error (`-32603`)**: Triggered on internal processing exceptions, preserving request ID.

---

## 5. Sample Protocol Exchange Log

```
--> REQUEST: {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
<-- RESPONSE: {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "netcoop-ai-mcp", "version": "1.0.0"}, "capabilities": {"tools": {}}}}

--> NOTIFICATION: {"jsonrpc": "2.0", "method": "notifications/initialized"}

--> REQUEST: {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_blast_radius", "arguments": {"device_id": "IITBBS-SW-MHR"}}}
<-- RESPONSE: {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "{\n  \"root_device_id\": \"IITBBS-SW-MHR\",\n  \"total_downstream_count\": 2,\n  \"downstream_device_ids\": [\"AP-MHR-W1\", \"AP-MHR-W2\"]\n}"}]}}

--> REQUEST: {"jsonrpc": "2.0", "id": 3, "method": "shutdown"}
<-- RESPONSE: {"jsonrpc": "2.0", "id": 3, "result": null}
Process exited with code 0.
```
