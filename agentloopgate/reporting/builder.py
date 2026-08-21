"""Deterministic Markdown/JSON decision card and SVG core charts."""

from __future__ import annotations

from decimal import Decimal
from html import escape
from pathlib import Path

from agentloopgate.contracts import canonical_digest, canonical_json_bytes
from agentloopgate.reporting.models import ReportArtifact, ReportData

_WIDTH = 760
_HEIGHT = 360


class DecisionReportBuilder:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def build(self, data: ReportData) -> ReportArtifact:
        directory = self.project_root / "reports" / data.experiment_id
        decision_json = directory / "decision.json"
        decision_markdown = directory / "decision.md"
        charts = [
            directory / "01_candidate_curve.svg",
            directory / "02_failure_funnel.svg",
            directory / "03_pool_comparison.svg",
            directory / "04_gate_waterfall.svg",
        ]
        record = data.decision.record
        self._write_bytes_once(
            decision_json,
            canonical_json_bytes(record) + b"\n",
        )
        decision_digest = canonical_digest(record)
        gate_rows = "\n".join(
            f"| {gate.name.value} | {gate.status.value} | `{gate.evidence_ref}` |"
            for gate in record.gates
        )
        markdown = (
            f"# Decision {record.decision_id}\n\n"
            f"- Candidate: `{record.candidate_id}`\n"
            f"- Baseline: `{record.baseline_snapshot_id}`\n"
            f"- Decision: **{record.decision.value}**\n"
            f"- Decision digest: `{decision_digest}`\n"
            f"- Reason: {data.decision.reason}\n\n"
            "## Promotion gates\n\n"
            "| Gate | Status | Evidence |\n"
            "|---|---|---|\n"
            f"{gate_rows}\n\n"
            "`SHIP_RECOMMENDED` is not a deployment; human CLI approval is still required.\n"
        )
        self._write_bytes_once(decision_markdown, markdown.encode())
        chart_payloads = [
            self._candidate_curve(data),
            self._failure_funnel(data),
            self._pool_comparison(data),
            self._gate_waterfall(data),
        ]
        for path, payload in zip(charts, chart_payloads, strict=True):
            self._write_bytes_once(path, payload.encode())
        report_digest = canonical_digest(
            {
                "decision": decision_digest,
                "markdown": markdown,
                "charts": chart_payloads,
            }
        )
        return ReportArtifact(
            schema_version="1.0",
            experiment_id=data.experiment_id,
            decision_json=decision_json,
            decision_markdown=decision_markdown,
            chart_paths=charts,
            report_digest=report_digest,
        )

    @staticmethod
    def _candidate_curve(data: ReportData) -> str:
        points = data.candidate_curve
        x_values = _x_positions(len(points))
        pass1 = " ".join(
            f"{x},{_metric_y(point.pass_1)}" for x, point in zip(x_values, points, strict=True)
        )
        passk = " ".join(
            f"{x},{_metric_y(point.pass_k)}" for x, point in zip(x_values, points, strict=True)
        )
        max_cost = max((point.mean_cost for point in points), default=Decimal(1)) or Decimal(1)
        costs = " ".join(
            f"{x},{_metric_y(point.mean_cost / max_cost)}"
            for x, point in zip(x_values, points, strict=True)
        )
        labels = "".join(
            _text(x, 330, point.label, anchor="middle")
            for x, point in zip(x_values, points, strict=True)
        )
        body = (
            _text(24, 28, "A0–An reliability and normalized cost", size=18)
            + _axes()
            + f'<polyline points="{pass1}" fill="none" stroke="#2563eb" stroke-width="3"/>'
            + f'<polyline points="{passk}" fill="none" stroke="#16a34a" stroke-width="3"/>'
            + f'<polyline points="{costs}" fill="none" stroke="#f97316" stroke-width="3"/>'
            + labels
            + _legend(
                [
                    (100, "Pass^1", "#2563eb"),
                    (210, "Pass^k", "#16a34a"),
                    (320, "Cost", "#f97316"),
                ]
            )
        )
        return _svg(body)

    @staticmethod
    def _failure_funnel(data: ReportData) -> str:
        points = data.failure_funnel
        maximum = max((point.count for point in points), default=1) or 1
        body = _text(24, 28, "Failure funnel: retrieval → policy → tool → state", size=18)
        for index, point in enumerate(points):
            y = 70 + index * 65
            width = int(560 * point.count / maximum)
            body += (
                _text(24, y + 24, point.stage)
                + f'<rect x="150" y="{y}" width="{width}" height="34" rx="6" fill="#7c3aed"/>'
                + _text(160 + width, y + 23, str(point.count))
            )
        return _svg(body)

    @staticmethod
    def _pool_comparison(data: ReportData) -> str:
        points = data.pool_comparison
        maximum = max((point.stable_tasks for point in points), default=1) or 1
        bar_width = max(18, min(60, 620 // len(points)))
        gap = 12
        body = _text(24, 28, "Candidate stable-task comparison by evaluation pool", size=18)
        for index, point in enumerate(points):
            x = 70 + index * (bar_width + gap)
            height = int(230 * point.stable_tasks / maximum)
            y = 300 - height
            color = "#0f766e" if index % 2 else "#0891b2"
            body += (
                f'<rect x="{x}" y="{y}" width="{bar_width}" height="{height}" fill="{color}"/>'
                + _text(x + bar_width // 2, y - 8, str(point.stable_tasks), anchor="middle")
                + _text(
                    x + bar_width // 2,
                    322,
                    f"{point.candidate_id}/{point.pool.value}",
                    anchor="middle",
                    size=10,
                )
            )
        body += '<line x1="50" y1="300" x2="730" y2="300" stroke="#64748b"/>'
        return _svg(body)

    @staticmethod
    def _gate_waterfall(data: ReportData) -> str:
        gates = data.decision.record.gates
        body = _text(24, 28, "Lexicographic promotion-gate waterfall", size=18)
        for index, gate in enumerate(gates):
            column = index % 3
            row = index // 3
            x = 30 + column * 245
            y = 65 + row * 88
            color = {
                "pass": "#16a34a",
                "fail": "#dc2626",
                "not_evaluated": "#94a3b8",
            }[gate.status.value]
            body += (
                f'<rect x="{x}" y="{y}" width="215" height="58" rx="8" fill="{color}"/>'
                + _text(x + 12, y + 25, gate.name.value, color="#ffffff", size=12)
                + _text(x + 12, y + 45, gate.status.value, color="#ffffff", size=11)
            )
        body += _text(30, 345, f"Final: {data.decision.record.decision.value}", size=16)
        return _svg(body)

    @staticmethod
    def _write_bytes_once(path: Path, payload: bytes) -> None:
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(f"report artifact conflict: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _svg(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" height="{_HEIGHT}" '
        f'viewBox="0 0 {_WIDTH} {_HEIGHT}">'
        '<rect width="100%" height="100%" fill="#f8fafc"/>'
        f"{body}</svg>"
    )


def _text(
    x: int,
    y: int,
    value: object,
    *,
    size: int = 12,
    color: str = "#0f172a",
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="system-ui,sans-serif" font-size="{size}" '
        f'fill="{color}" text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def _axes() -> str:
    return (
        '<line x1="60" y1="60" x2="60" y2="305" stroke="#64748b"/>'
        '<line x1="60" y1="305" x2="730" y2="305" stroke="#64748b"/>'
    )


def _metric_y(value: Decimal) -> int:
    return 305 - int(230 * value)


def _x_positions(count: int) -> list[int]:
    if count == 1:
        return [395]
    return [70 + int(index * 650 / (count - 1)) for index in range(count)]


def _legend(items: list[tuple[int, str, str]]) -> str:
    return "".join(
        f'<line x1="{x}" y1="48" x2="{x + 24}" y2="48" stroke="{color}" stroke-width="3"/>'
        + _text(x + 30, 52, label)
        for x, label, color in items
    )
