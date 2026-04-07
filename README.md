# G2-M6: Integration + Load/Soak Testing Pack (Comprehensive)

This folder is a **self-contained and project-integrated implementation** for:

1. End-to-end validation: **order events -> matching -> trades**
2. Scale/soak harness targeting **500K orders / 2M trades**
3. Latency hotspot extraction + optimization recommendations report

It is designed to fit your existing simulator architecture (Exchange API + telemetry endpoints), and integrate with your existing dashboard/reporting flow without touching core service code.

---

## Folder Contents

- `requirements.txt`  
  Python dependencies required by this package.

- `common.py`  
  Shared integration utilities: endpoint paths, market-ready actions, safe JSON parsing.

- `scenario.example.json`  
  Scenario-driven config for target scale and runtime knobs.

- `scenario.local.json`  
  Tuned for local source-mode execution.

- `scenario.docker.json`  
  Tuned for Docker-based execution.

- `e2e_order_to_trade_test.py`  
  E2E validator that submits opposing orders, tracks lifecycle, and confirms trade visibility.

- `soak_runner.py`  
  High-volume soak runner for long runs and target checks (500K/2M by default in scenario), plus dashboard-compatible JSON output.

- `latency_hotspot_report.py`  
  Pulls live performance metrics and emits a markdown hotspot report with actionable recommendations.

- `run_g2_m6_suite.py`  
  One-command suite orchestration (E2E -> Soak -> Hotspot report -> suite summary).

- `run-g2-m6.ps1`  
  PowerShell wrapper aligned with your repo tooling style.

---

## What This Implements (Mapped to Your Requirement)

### 1) End-to-end test: Order events -> matching -> trades

Implemented by `e2e_order_to_trade_test.py`:

- Opens market/risk/circuit-breakers using admin APIs (best effort)
- Submits BUY + SELL against the same symbol and price
- Polls order status and trade endpoints
- Produces machine-readable JSON output with:
  - order references
  - lifecycle snapshot
  - trade detection flag
  - end-to-end elapsed time

---

### 2) Stress/soak tests to reach target scale (500K orders / 2M trades)

Implemented by `soak_runner.py` + `scenario.example.json`:

- Supports configurable targets:
  - `target_orders`: default `500000`
  - `target_trades`: default `2000000`
- Uses concurrent order submission with balanced BUY/SELL flow to encourage matching
- Tracks:
  - attempted / accepted / rejected orders
  - request latency percentiles (p50, p95, p99)
  - achieved throughput
  - target met booleans
- Writes a detailed JSON report to `reports/soak-report.json`

Important: The script is implementation-complete for these targets. Actual achievement of 2M trades depends on backend matching behavior, symbol liquidity, and runtime capacity.

---

### 3) Measure/document latency hotspots + optimization recommendations

Implemented by `latency_hotspot_report.py`:

- Pulls metrics from:
  - `/api/system/performance`
  - `/api/system/performance/latency`
  - `/metrics`
- Ranks operations by P99 latency
- Generates:
  - `reports/latency-hotspot-report.md`
  - raw evidence snapshots:
    - `reports/performance-summary.json`
    - `reports/performance-latency.json`
    - `reports/telemetry.json`
- Adds recommendations per hotspot class:
  - DB-heavy
  - FIX parsing/sending
  - matching engine
  - WebSocket broadcast
  - order lifecycle paths

---

## Quick Start

From repository root:

```powershell
cd .\g2-m6-integration-load-soak
python -m pip install -r .\requirements.txt
```

### Recommended integrated run (single command)

```powershell
.\run-g2-m6.ps1
```

This runs all three phases and writes a consolidated `reports/suite-summary.json`.

### A) Run End-to-End validator

```powershell
python .\e2e_order_to_trade_test.py
```

Expected output: JSON with success, order refs, lifecycle, and trade visibility.

### B) Run Soak/Scale test

```powershell
python .\soak_runner.py --scenario .\scenario.example.json --out .\reports\soak-report.json
```

Expected output:

- Progress logs during execution
- Final summary in console
- Full structured report in `reports/soak-report.json`
- Dashboard-compatible JSON auto-written to:
  - `..\loadtest-dashboard\public\loadtest-results.json`

### C) Generate Latency Hotspot report

```powershell
python .\latency_hotspot_report.py --base-url http://localhost:8090 --out-dir .\reports
```

Expected output:

- `reports/latency-hotspot-report.md`
- raw telemetry/performance snapshots in `reports/`

### D) Full suite orchestration (Python entrypoint)

```powershell
python .\run_g2_m6_suite.py --scenario .\scenario.local.json --base-url http://localhost:8090 --reports-dir reports
```

---

## Scenario Configuration Reference

`scenario.example.json` fields:

- `base_url`: exchange backend base URL
- `target_orders`: total accepted orders target
- `target_trades`: trade count target
- `symbol`: working symbol for soak flow
- `client_id_prefix`: tag prefix for generated clients
- `orders_per_batch`: submission chunk size
- `concurrency`: parallel request workers
- `poll_interval_seconds`: polling interval for state checks
- `max_wait_seconds`: max wait for completion blocks
- `latency_sla_ms`: desired p50/p95/p99 thresholds

Suggested profile usage:

- Source mode: `scenario.local.json`
- Docker mode: `scenario.docker.json`

---

## Output Artifacts

This implementation standardizes output in `g2-m6-integration-load-soak/reports/`:

- `soak-report.json`: target-scale execution outcome and latency distribution
- `latency-hotspot-report.md`: ranked bottlenecks and recommendations
- `performance-summary.json`, `performance-latency.json`, `telemetry.json`: evidence snapshots
- `suite-summary.json`: integrated execution status for all G2-M6 phases

These are ready to be attached in project documentation or milestone submissions.

---

## Design Notes

- This folder intentionally does not modify existing core services.
- All scripts use existing public/admin endpoints already present in your backend.
- Endpoint usage is centralized in `common.py` for maintainability.
- The soak runner is optimized for controllability and observability (clear progress + deterministic output schema), which is ideal for milestone reporting.
- Dashboard integration is built-in by exporting results to your existing `loadtest-dashboard/public/loadtest-results.json`.

---

## Integration With Existing Project

This pack is aligned with your current project assets:

- Uses Exchange API conventions already used by root scripts:
  - `/api/orders/orchestrated`
  - `/api/system/*`
- Reuses backend metrics endpoints already exposed in `SystemMetricsRest`:
  - `/api/system/performance`
  - `/api/system/performance/latency`
- Reuses telemetry endpoint exposed in `TelemetryResource`:
  - `/metrics`
- Writes dashboard JSON to existing path consumed by React dashboard:
  - `loadtest-dashboard/public/loadtest-results.json`

Because of this, you can run this pack independently or alongside your existing root-level validation scripts without conflicting changes.

---

## Suggested Submission Evidence for G2-M6

For your milestone report, include:

1. `soak-report.json` (proves target attempt + achieved throughput/latencies)
2. `latency-hotspot-report.md` (hotspots + optimization plan)
3. E2E output JSON from `e2e_order_to_trade_test.py` (order->trade path proof)
4. `suite-summary.json` (single file showing pass/fail status of all phases)

This gives full, auditable evidence for all 3 required bullets in G2-M6.
