# Security & Trusted Execution Adapter Registry — Closure Report

## 1. Executive Summary & Security Objectives
NetCoop AI operates in a high-stakes campus network environment where unauthorized or automated physical switch reconfigurations could disrupt campus connectivity. Release 5 implements a strict **Zero-Trust Execution Security Architecture**:
1. Zero hardcoded authorization keys or operator secrets in source code.
2. Canonical HMAC-SHA256 authorization records binding operator, incident, action IDs, network tier, nonce, and scope.
3. Registered Execution Adapter Registry verifying adapter identities and cryptographic receipt signatures.
4. Mandatory measured post-execution telemetry checks before declaring real recovery.

---

## 2. Operator Authorization Record Specification

```python
class OperatorAuthorizationRecord(BaseModel):
    operator_id: str
    incident_id: str
    action_ids: List[str]
    authorized_network_tier: str
    timestamp: datetime
    nonce: str
    authorization_scope: str = "CORRECTIVE_REMEDIATION"
    auth_token: str
```

### Cryptographic Signature Binding
Signatures are generated using HMAC-SHA256 over canonical sorted JSON:
$$\text{token} = \text{HMAC-SHA256}(K_{\text{secret}}, \text{canonical\_json}(\text{operator\_id}, \text{incident\_id}, \text{action\_ids}, \text{tier}, \text{timestamp}, \text{nonce}, \text{scope}))$$

### Security Guards Enforced
- **Clock Skew Guard**: Rejects tokens dated more than $60\text{s}$ into the future.
- **TTL Expiration Guard**: Rejects tokens older than $300\text{s}$.
- **Replay Protection**: Nonces are registered and consumed upon verified execution; replay attempts are rejected immediately.
- **Strict Scope Binding**: Rejects tokens when `incident_id`, `action_id`, or `network_tier` does not match the target remediation action.

---

## 3. Registered Execution Adapter Registry

In Release 5, unverified execution claims are prohibited. Every live execution requires proof from a registered adapter:

```python
class ExecutionAdapterRegistry:
    # Default trusted adapters:
    # 1. ADAPTER-CISCO-IOS-XE   (Cisco IOS-XE NETCONF/SSH Driver)
    # 2. ADAPTER-LINUX-SYSTEMD  (Linux Core Services Controller)
    # 3. ADAPTER-MOCK-TESTING   (Automated Testing Sandbox Driver)
```

### Execution Receipt Verification Contract
An `ExecutionReceipt` must be signed by the adapter:
$$\text{sig}_{\text{adapter}} = \text{HMAC-SHA256}(K_{\text{adapter}}, \text{canonical\_json}(\text{execution\_id}, \text{incident\_id}, \text{action\_id}, \text{device}, \text{result}))$$

The lifecycle state machine verifies both:
1. `receipt.verify_against_authorization(auth_record)`
2. `ExecutionAdapterRegistry.verify_receipt(receipt)`

---

## 4. Remediation Lifecycle State Machine (10 States)

$$\text{RECOMMENDED} \to \text{SIMULATED} \to \text{APPROVAL\_PENDING} \to \text{APPROVED} \to \text{REAL\_EXECUTION\_PENDING} \to \text{REAL\_EXECUTED} \to \text{REAL\_RECOVERY\_VERIFIED}$$

- Default mode is **Safe Simulation-Only Mode** (`NETCOOP_ENABLE_LIVE_EXECUTION=0`).
- Transition to `REAL_EXECUTED` strictly requires:
  - `NETCOOP_ENABLE_LIVE_EXECUTION == 1`
  - Valid `OperatorAuthorizationRecord` with unconsumed nonce
  - Genuine, cryptographically verified `ExecutionReceipt` from a registered adapter.
- Transition to `REAL_RECOVERY_VERIFIED` strictly requires measured post-action telemetry (packet loss $< 2.0\%$, interface errors $< 10$).

---

## 5. Verification Evidence

- 18/18 security and lifecycle tests passing in `test_remediation_lifecycle.py` and `test_remediation_security.py`.
- Verified in `test_end_to_end_scenarios.py` (Scenarios 18, 19).
