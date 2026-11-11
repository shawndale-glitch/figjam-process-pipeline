"""Check procedure.yaml files against governance/workflow-rules.yaml -> procedure (P1-P9, PW1-PW2).

Usage:
  python tooling/procedure_check.py                       # every procedures/*/*/procedure.yaml
  python tooling/procedure_check.py path/to/procedure.yaml --report procedure-report.md

Errors block at any status; warnings block in-review and validated (same as the workflow linter).
Exit codes: 0 = no blocking findings, 1 = blocking findings, 2 = usage error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import procedure_core as pc  # noqa: E402
from workflow_core import REPO, load_yaml  # noqa: E402


def blocking(spec: dict, findings) -> list:
    status = (spec.get("procedure") or {}).get("status", "draft")
    return [f for f in findings if f.severity == "error" or status in ("in-review", "validated")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    files = a.files or pc.all_specs()
    if not files:
        print("No procedures found.")
        return 0
    lines = ["# Procedure check", "", f"Rules: governance/workflow-rules.yaml -> procedure (rules_version {load_yaml(REPO / 'governance' / 'workflow-rules.yaml')['rules_version']})", ""]
    failed = 0
    for path in files:
        spec = load_yaml(path)
        findings = pc.lint(spec)
        block = blocking(spec, findings)
        failed += bool(block)
        rel = path.resolve().relative_to(REPO) if path.resolve().is_relative_to(REPO) else path
        status = (spec.get("procedure") or {}).get("status", "?")
        head = f"{'FAIL' if block else 'PASS'}  {rel}  ({status}; {sum(x.severity == 'error' for x in findings)} errors, {sum(x.severity == 'warning' for x in findings)} warnings)"
        print(head)
        lines.append(f"## {rel}\n\n{head}\n")
        for x in findings:
            row = f"{x.rule} [{x.severity}] {x.node or '-'}: {x.message}"
            print(f"      {row}")
            lines.append(f"- {row}")
        lines.append("")
    if a.report:
        a.report.write_text("\n".join(lines), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
