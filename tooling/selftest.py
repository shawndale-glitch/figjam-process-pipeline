"""Library self-test: every published component must pass intake with 0 findings,
and every rule must fire on a board, workbook or procedure built to break it.

Usage: python tooling/selftest.py   (exit 0 = pass)
Boards: examples/library-selftest/*.board.json and examples/patterns/*.board.json (see their READMEs).
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
import procedure_core  # noqa: E402

BOARDS = sorted((core.REPO / "examples" / "library-selftest").glob("*.board.json"))
PATTERNS = sorted((core.REPO / "examples" / "patterns").glob("*.board.json"))


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
    b = copy.deepcopy(base); first(b, "Data and systems/Document")["props"].update({"Link": "C:\\Users\\me\\contract.docx", "Show link": True})
    failed += expect("W9 local-path document link is flagged", core.build(b).findings, {"W9"})
    b = copy.deepcopy(base); doc = first(b, "Data and systems/Document")
    doc["props"].update({"Link": "https://example.sharepoint.com/sites/docs/Purchase-order.docx", "Show link": True})
    res = core.build(b)
    exported = any(n.get("url", "").endswith("Purchase-order.docx") for n in res.workflow["nodes"])
    ok = exported and not res.findings
    print(f"{'PASS' if ok else 'FAIL'}  document link is exported to workflow.yaml  ({'url present' if exported else 'url missing'}, {len(res.findings)} findings)")
    failed += not ok
    failed += first_session_mistakes(base)
    return failed


def first_session_mistakes(base: dict) -> int:
    """The mistakes seen most on real first-session boards must all be caught in one run:
    the legend pasted into the process section (a second start event and nested sections),
    a decision exit without a condition, a solid line to a system, and a system left unlinked."""
    b = copy.deepcopy(base)
    start = next(i for i in b["instances"] if i["component"] == "Events/Start event")
    b["instances"].append({**copy.deepcopy(start), "id": "9:100", "props": {"Show label": True, "Label": "Order received"}})
    b["other"].append({"id": "9:101", "type": "SECTION", "name": "", "x": 3000, "y": 40, "w": 360, "h": 300})
    xor_exit = next(c for c in b["connectors"] if c["label"])
    xor_exit["label"] = ""
    to_system = next(c for c in b["connectors"] if c["dashed"] and c["from"] in
                     {i["id"] for i in b["instances"] if i["component"] == "Data and systems/System"})
    to_system["dashed"] = False
    system = next(i for i in b["instances"] if i["component"] == "Data and systems/System")
    b["instances"].append({**copy.deepcopy(system), "id": "9:102", "props": {"Label": "Spreadsheet"}})
    return expect("first-session mistakes are all caught", core.build(b).findings, {"R2", "R3", "R4", "R5", "W5"})


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
        ws.append(["P2P-03", "Invoice approval", "Core process", "Finance lead", "En revisión", "2026-10-20", link, None, "X"])   # published in workflows/ as in-review
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


def procedures() -> int:
    """Every example procedure passes with no errors; each P-rule fires on a copy built to break it."""
    failed = 0
    for path in procedure_core.all_specs():
        errors = [f for f in procedure_core.lint(core.load_yaml(path)) if f.severity == "error"]
        print(f"{'PASS' if not errors else 'FAIL'}  procedure {path.parent.name} has no errors  ({len(errors)} errors)")
        for f in errors:
            print(f"      {f.rule} {f.node}: {f.message}")
        failed += bool(errors)
    base = core.load_yaml(core.REPO / "procedures" / "procure-to-pay" / "P2P-03-P01" / "procedure.yaml")
    lint = procedure_core.lint
    b = copy.deepcopy(base); b["procedure"]["environment"] = "production"
    failed += expect("P2 production environment is rejected", lint(b), {"P2"})
    b = copy.deepcopy(base); b["steps"][1]["say"]["en"] = "TODO"
    failed += expect("P3 English text left as TODO is rejected", lint(b), {"P3"})
    b = copy.deepcopy(base); del b["steps"][1]["say"]["es"]
    failed += expect("P3 missing Spanish text is rejected", lint(b), {"P3"})
    b = copy.deepcopy(base); del b["steps"][2]["expect"]
    failed += expect("P4 step without expected result is rejected", lint(b), {"P4"})
    b = copy.deepcopy(base); b["steps"][2]["do"]["target"] = {"css": "#search-form button"}
    failed += expect("P5 CSS locator is rejected", lint(b), {"P5"})
    b = copy.deepcopy(base); b["steps"][1]["do"]["value"] = "ana.garcia@example.com"
    failed += expect("P7 personal data typed into a field is rejected", lint(b), {"P7"})
    b = copy.deepcopy(base); b["fixtures"]["invoice"]["supplier"] = "Garcia Logistics SL"
    failed += expect("P7 fixture party without a test name is rejected", lint(b), {"P7"})
    b = copy.deepcopy(base); b["procedure"]["system"] = "erp-live"
    failed += expect("P8 unknown system is rejected", lint(b), {"P8"})
    b = copy.deepcopy(base); b["procedure"].update(role="Night auditor", step_ref="Print invoices")
    failed += expect("P6/P8 role and step must exist on the linked process", lint(b), {"P6", "P8"})
    b = copy.deepcopy(base); b["steps"] += [copy.deepcopy(base["steps"][2]) for _ in range(10)]
    failed += expect("PW1 more than 12 steps is flagged", lint(b), {"PW1"})
    b = copy.deepcopy(base); b["procedure"]["process"] = "OPS-099"
    failed += expect("PW2 a process not yet in workflows/ is flagged", lint(b), {"PW2"})
    b = copy.deepcopy(base); b["procedure"]["starts_from"] = "P2P-03-P99"
    failed += expect("P9 starts_from an unknown procedure is rejected", lint(b), {"P9"})
    b = copy.deepcopy(base); b["procedure"]["starts_from"] = base["procedure"]["id"]
    failed += expect("P9 starts_from that loops back is rejected", lint(b), {"P9"})
    other = core.load_yaml(core.REPO / "procedures" / "procure-to-pay" / "P2P-03-P02" / "procedure.yaml")
    b = copy.deepcopy(other); b["fixtures"] = {"bill": b["fixtures"]["invoice"]}
    failed += expect("P9 the opening's fixtures must be declared too", lint(b), {"P9"})
    return failed


def main() -> int:
    failed = 0
    for path in BOARDS + PATTERNS:
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
    failed += procedures()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
