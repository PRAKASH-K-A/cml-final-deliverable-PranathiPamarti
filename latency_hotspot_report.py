import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from common import DEFAULT_ENDPOINTS, make_url, parse_json_or_default


def get_json(session: requests.Session, base_url: str, path: str) -> Dict[str, Any]:
    url = make_url(base_url, path)
    response = session.get(url, timeout=20)
    response.raise_for_status()
    return parse_json_or_default(response, {})


def extract_hotspots(latency_map: Dict[str, Any]) -> List[Tuple[str, float, float, float]]:
    """
    Returns sorted list of (operation, p50, p95, p99) in milliseconds, descending by p99.
    """
    rows: List[Tuple[str, float, float, float]] = []
    for op, stats in latency_map.items():
        try:
            p50 = float(stats.get("p50Ms", 0.0))
            p95 = float(stats.get("p95Ms", 0.0))
            p99 = float(stats.get("p99Ms", 0.0))
            rows.append((op, p50, p95, p99))
        except Exception:
            continue
    rows.sort(key=lambda x: x[3], reverse=True)
    return rows


def recommendations_for(operation: str) -> str:
    op = operation.lower()
    if "db" in op:
        return "Use batch writes, index critical predicates, and separate read/write pools."
    if "fix" in op:
        return "Reduce parser allocations, reuse objects, and tune socket/read buffer sizes."
    if "match" in op:
        return "Optimize order-book data structures and reduce lock contention on hot symbols."
    if "ws" in op or "websocket" in op:
        return "Batch broadcasts, reduce payload size, and apply backpressure on slow clients."
    if "order" in op:
        return "Minimize synchronous validations, cache reference data, and short-circuit rejects early."
    return "Profile this path with allocation + CPU flamegraphs, then optimize the top offenders first."


def build_markdown(
    base_url: str,
    summary: Dict[str, Any],
    latency: Dict[str, Any],
    telemetry: Dict[str, Any],
    scenario: Dict[str, Any],
) -> str:
    hotspots = extract_hotspots(latency)
    top = hotspots[:10]

    lines: List[str] = []
    lines.append("# G2-M6 Latency Hotspot Report")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- Target service: `{base_url}`")
    lines.append("- Source endpoints: `/api/system/performance`, `/api/system/performance/latency`, `/metrics`")
    lines.append("")
    lines.append("## Current Summary")
    lines.append(f"- Total operations: `{summary.get('totalOperations', 'n/a')}`")
    lines.append(f"- Average latency (ms): `{summary.get('avgLatencyMs', 'n/a')}`")
    lines.append(f"- Throughput (ops/sec): `{summary.get('throughputOpsPerSec', 'n/a')}`")
    sla = scenario.get("latency_sla_ms", {})
    if sla:
        lines.append(f"- SLA target p50/p95/p99 (ms): `{sla.get('p50', 'n/a')}/{sla.get('p95', 'n/a')}/{sla.get('p99', 'n/a')}`")
    lines.append("")
    lines.append("## Top Latency Hotspots (by P99)")
    lines.append("| Operation | P50 ms | P95 ms | P99 ms | Recommendation |")
    lines.append("|---|---:|---:|---:|---|")
    for op, p50, p95, p99 in top:
        lines.append(
            f"| `{op}` | {p50:.3f} | {p95:.3f} | {p99:.3f} | {recommendations_for(op)} |"
        )
    lines.append("")
    lines.append("## Additional Telemetry Notes")
    lines.append("- FIX metrics keys: " + ", ".join(sorted((telemetry.get("fix") or {}).keys())) if isinstance(telemetry, dict) else "- n/a")
    lines.append("- Matching metrics keys: " + ", ".join(sorted((telemetry.get("matching") or {}).keys())) if isinstance(telemetry, dict) else "- n/a")
    lines.append("- WebSocket metrics keys: " + ", ".join(sorted((telemetry.get("websocket") or {}).keys())) if isinstance(telemetry, dict) else "- n/a")
    lines.append("")
    lines.append("## Optimization Plan (Prioritized)")
    lines.append("1. Tackle top 2 operations by P99 and measure improvement after each change.")
    lines.append("2. For DB-heavy hotspots, apply batching and index verification before code-level changes.")
    lines.append("3. For matching/fix paths, run CPU + allocation profiling under realistic load.")
    lines.append("4. Add SLO gates in CI: fail if P95/P99 regress beyond threshold.")
    lines.append("")
    lines.append("## Evidence")
    lines.append("Raw payloads are stored next to this report as JSON for traceability.")
    lines.append("")
    lines.append("## Integration Notes")
    lines.append("- This report format is compatible with the `g2-m6-integration-load-soak/reports` workflow.")
    lines.append("- Pair this output with `soak-report.json` for complete G2-M6 submission evidence.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate G2-M6 latency hotspot report")
    parser.add_argument("--base-url", default="http://localhost:8090")
    parser.add_argument(
        "--scenario",
        default=str(Path(__file__).with_name("scenario.example.json")),
        help="Scenario JSON to include SLA and target context",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).with_name("reports")),
        help="Output directory for markdown + raw json snapshots",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scenario = {}
    scenario_path = Path(args.scenario)
    if scenario_path.exists():
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    with requests.Session() as session:
        perf_summary = get_json(session, args.base_url, DEFAULT_ENDPOINTS.perf_summary)
        perf_latency = get_json(session, args.base_url, DEFAULT_ENDPOINTS.perf_latency)
        telemetry = get_json(session, args.base_url, DEFAULT_ENDPOINTS.telemetry)

    # Persist raw evidence.
    (out_dir / "performance-summary.json").write_text(json.dumps(perf_summary, indent=2), encoding="utf-8")
    (out_dir / "performance-latency.json").write_text(json.dumps(perf_latency, indent=2), encoding="utf-8")
    (out_dir / "telemetry.json").write_text(json.dumps(telemetry, indent=2), encoding="utf-8")

    # Build markdown.
    markdown = build_markdown(args.base_url, perf_summary, perf_latency, telemetry, scenario)
    report_path = out_dir / "latency-hotspot-report.md"
    report_path.write_text(markdown, encoding="utf-8")
    print(f"[done] report written to {report_path}")


if __name__ == "__main__":
    main()
