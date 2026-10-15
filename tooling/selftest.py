"""Library self-test: every published component must pass intake with 0 findings,
and every rule must fire on a board (or workbook) built to break it.

Usage: python tooling/selftest.py   (exit 0 = pass)
Boards: examples/library-selftest/*.board.json (see its README).
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_core as core  # noqa: E402
import inventory_check  # noqa: E402

BOARDS = sorted((core.REPO / "examples" / "library-selftest").glob("*.board.json"))


def expect(name: str, findings, rules: set[str]) -> int:
    """PASS when every rule in `rules` is among the findings."""
    got = {f.rule for f in findings}
    ok = rules <= got
    print(f"{'PASS' if ok else 'FAIL'}  {name}  (expects {', '.join(sorted(rules))}; got {', '.join(sorted(got)) or 'none'})")
    return not ok


def broken_boards(base: dict) -> int:
    """Each new lint rule must fire on a copy of a clean board that breaks it."""
    failed = 0
    first = lambda b, comp: next(i for i in b["instances"] if i["component"] == comp)
    b = copy.deepcopy(base); first(b, "Activities/Activity")["props"]["Label"] = "Verb + object"
    failed += expect("R9 default label is rejected", core.build(b).findings, {"R9"})
    b = copy.deepcopy(base); first(b, "Markers/Swimlane")["props"]["Role"] = "Role / team"
    failed += expect("R9 default lane role is rejected", core.build(b).findings, {"R9"})
    b = copy.deepcopy(base); first(b, "Template/Header block")["props"]["Owner"] = "Role or name"
    failed += expect("R9 default header field is rejected", core.build(b).findings, {"R9"})
    b = copy.deepcopy(base); first(b, "Gateways/Decision (XOR)")["props"]["Question"] = "Check amount"
    failed += expect("W7 decision that is not a question is flagged", core.build(b).findings, {"W7"})
    b = copy.deepcopy(base); act = first(b, "Activities/Activity")
    for n in range(16):
        b["instances"].append({**copy.deepcopy(act), "id": f"9:{n}", "props": {"Label": f"Do step {n}"}})
    failed += expect("W8 more than 15 activities is flagged", core.build(b).findings, {"W8"})
    return failed


def workbooks() -> int:
    """A well-formed inventory passes; a broken one fails with the right rules."""
    from openpyxl import Workbook

    failed = 0
    head = ["ID del proceso", "Proceso", "Categoría", "Responsable", "Estado", "Fecha tentativa", "Enlace FigJam", "DEA", "Staff"]
    link = "https://www.figma.com/board/EXAMPLEFILEKEY0000000000/Process-template?node-id=2-131"
    with tempfile.TemporaryDirectory() as tmp:
        wb = Workbook(); ws = wb.active; ws.title = "Inventario"
        ws.append(["Process inventory (self-test)"]); ws.append([]); ws.append(head)
        ws.append(["P2P-01", "Invoice capture", "Core process", "Finance lead", "Borrador", date(2026, 10, 13), link, "X", "X"])
        ws.append(["P2P-03", "Invoice approval", "Core process", "Finance lead", "Borrador", "2026-10-20", link, None, "X"])
        ws.append(["Clave: X = el área participa en la sesión"])
        good = Path(tmp) / "good.xlsx"; wb.save(good)
        findings, _ = inventory_check.check(good)
        ok = not findings
        print(f"{'PASS' if ok else 'FAIL'}  well-formed inventory passes  ({len(findings)} findings)")
        for f in findings:
            print(f"      {f.rule} {f.label}: {f.message}")
        failed += not ok

        wb = Workbook(); ws = wb.active
        ws.append(head + ["Equipo Staff"])
        ws.append([1, "Invoice capture", "Core process", "Finance lead", "Pendiente", "05/11/2026", "", "X", "X", None])
        ws.append(["P2P-04", "Supplier payment", "Core process", "Finance lead", "Aprobado", "2026-10-15", "", "X", None, None])
        bad = Path(tmp) / "bad.xlsx"; wb.save(bad)
        findings, _ = inventory_check.check(bad)
        failed += expect("broken inventory is rejected", findings, {"I2", "I3", "I4", "I5", "I6", "I7"})
    return failed


def main() -> int:
    failed = 0
    for path in BOARDS:
        res = core.build(json.loads(path.read_text(encoding="utf-8")))
        probe = json.loads(json.dumps(res.workflow))
        probe["process"]["version"] = "0.0.1"
        problems = [f"{f.rule} {f.label}: {f.message}" for f in res.findings] + [f"SCHEMA {e}" for e in core.schema_errors(probe)]
        types = sorted({n["type"] for n in res.workflow["nodes"]})
        print(f"{'PASS' if not problems else 'FAIL'}  {path.name}  ({len(res.workflow['nodes'])} nodes, {len(res.workflow['flows'])} flows; types: {', '.join(types)})")
        for p in problems:
            print(f"      {p}")
        failed += bool(problems)
    # A retired arrow component must be rejected with R2
    board = json.loads(BOARDS[0].read_text(encoding="utf-8"))
    board["instances"].append({"id": "0:0", "component": "_Conectores/Flujo de secuencia", "component_key": "x", "props": {}, "texts": [], "x": 0, "y": 0, "w": 1, "h": 1})
    rejected = any(f.rule == "R2" and "Retired" in f.message for f in core.build(board).errors)
    print(f"{'PASS' if rejected else 'FAIL'}  retired arrow component is rejected")
    failed += not rejected
    failed += broken_boards(json.loads(BOARDS[0].read_text(encoding="utf-8")))
    failed += workbooks()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
