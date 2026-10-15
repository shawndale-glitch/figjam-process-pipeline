"""FigJam board.json -> lint -> version -> resting point.

Usage:
  python tooling/workflow_intake.py path/to/board.json [--report report.md] [--dry-run]
  python tooling/workflow_intake.py --url "<FigJam section link>" [--report report.md] [--github-output]

--url extracts the section through the Figma REST API (needs FIGMA_TOKEN).
--github-output writes outcome, process_id, version, area and bump to $GITHUB_OUTPUT.

Exit codes: 0 = accepted and written, 1 = rejected (nothing written to workflows/ or docs/),
2 = usage error. Rules: governance/workflow-rules.yaml.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_core as core  # noqa: E402
import workflow_render as render  # noqa: E402


def report(res: core.Result, board: dict, version_lines: list[str], verification: list[str]) -> str:
    src = board["source"]
    key = src["figma_file_key"]
    L = ["# Workflow intake report", "", "## Source", "",
         f"- FigJam file `{key}`, section `{src['section_id']}` ({src['section_name']})",
         f"- Exported {src['exported_at']} with {board.get('extractor', '?')}", "",
         f"## Findings: {len(res.errors)} errors, {len(res.warnings)} warnings", ""]
    if not res.findings:
        L.append("None.")
    for f in res.errors + res.warnings:
        link = f" ([open in FigJam]({core.deep_link(key, f.node)}))" if f.node else ""
        L.append(f"- {'❌' if f.severity == 'error' else '⚠️'} **{f.rule}** «{f.label}» {f.message}{link}")
    if res.fixes:
        L += ["", "### Autofixes applied (whitespace and dates only)", ""]
        L += [f"- `{x.node}` {x.field}: {x.before!r} → {x.after!r}" for x in res.fixes]
    L += ["", "## Version", ""] + (version_lines or ["Not computed (rejected)."])
    L += ["", "## Verification", ""] + verification
    L += ["", "> A clean lint means the diagram is well-formed and machine-readable. It is **not** business approval: "
          "status `validated` comes only from a business SME's PR approval."]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("board", nargs="?")
    ap.add_argument("--url", help="FigJam link to the process section (REST extraction)")
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--github-output", action="store_true")
    a = ap.parse_args()
    if bool(a.board) == bool(a.url):
        ap.error("give either a board.json path or --url")

    if a.url:
        import figma_rest
        board = figma_rest.extract(a.url)
    else:
        board = json.loads(Path(a.board).read_text(encoding="utf-8"))
    rc = run(board, a)
    return rc


def emit(a, **kv) -> None:
    """Write step outputs for GitHub Actions."""
    if not a.github_output:
        return
    import os
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in kv.items())
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(lines)
    else:
        print(lines, end="")


def run(board: dict, a) -> int:
    res = core.build(board)
    wf = res.workflow
    verification = []

    # Schema check runs on a provisional version so only real contract problems show.
    probe = json.loads(json.dumps(wf))
    probe["process"]["version"] = "0.0.1"
    serr = core.schema_errors(probe)
    for e in serr:
        res.findings.append(core.Finding("SCHEMA", "error", None, "", e))
    verification.append(f"- Schema `schemas/workflow.schema.json`: {'pass' if not serr else f'{len(serr)} error(s)'}")

    blocking = res.errors + (res.warnings if wf["process"]["status"] in ("in-review", "validated") else [])
    verification.append(f"- Lint: {len(res.errors)} errors, {len(res.warnings)} warnings → "
                        + ("**rejected**" if blocking else "**accepted**")
                        + f" (warnings block only in-review/validated; status is `{wf['process']['status']}`)")
    if blocking:
        text = report(res, board, [], verification)
        (Path(a.report).write_text(text, encoding="utf-8") if a.report else print(text))
        emit(a, outcome="rejected", process_id=wf["process"]["id"], area=wf["process"]["area"], version="", bump="")
        return 1

    p = core.paths(wf)
    prev_path = p["dir"] / "workflow.yaml"
    old = yaml.safe_load(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else None
    bump, reasons = core.diff(old, wf)
    wf["process"]["version"] = core.next_version(old, wf, bump)
    declared = wf["process"]["declared_version"].lstrip("vV")
    declared_ok = tuple(int(x) for x in (declared + ".0").split(".")[:3]) >= tuple(int(x) for x in wf["process"]["version"].split("."))
    vlines = [f"- Last version: `{old['process']['version']}`" if old else "- Last version: none (first export)",
              f"- Change: **{bump}**" + (f" — {reasons[0]}" if reasons else "")]
    vlines += [f"  - {r}" for r in reasons[1:]]
    vlines += [f"- Computed version: `{wf['process']['version']}`",
               f"- Header declares: `{wf['process']['declared_version']}` → " + ("OK" if declared_ok else f"**update the board header to v{wf['process']['version']}**")]
    if not declared_ok:  # versioning.header_check: fail and report the computed value
        hdr = next((i["id"] for i in board["instances"] if i["component"] == core.HEADER_COMPONENT), None)
        res.findings.append(core.Finding("VERSION", "error", hdr, wf["process"]["declared_version"],
                                         f"Header 'Versión' is lower than the computed version; set it to v{wf['process']['version']} and re-run"))
        verification.append("- Header version check: **rejected**; nothing written.")
        text = report(res, board, vlines, verification)
        (Path(a.report).write_text(text, encoding="utf-8") if a.report else print(text))
        emit(a, outcome="rejected", process_id=wf["process"]["id"], area=wf["process"]["area"], version=wf["process"]["version"], bump=bump)
        return 1

    if bump == "none" and old and old["process"]["content_hash"] == wf["process"]["content_hash"]:
        verification.append("- No behavioural change since the last export; nothing written.")
        text = report(res, board, vlines, verification)
        (Path(a.report).write_text(text, encoding="utf-8") if a.report else print(text))
        emit(a, outcome="unchanged", process_id=wf["process"]["id"], area=wf["process"]["area"], version=wf["process"]["version"], bump="none")
        return 0

    if not a.dry_run:
        p["dir"].mkdir(parents=True, exist_ok=True)
        (p["dir"] / "board.json").write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        header = (f"# Generated by tooling/workflow_intake.py from FigJam. Do not edit; change the board and re-run intake.\n"
                  f"# Rules: governance/workflow-rules.yaml  Schema: schemas/workflow.schema.json\n")
        prev_path.write_text(header + yaml.safe_dump(wf, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        cl = p["dir"] / "CHANGELOG.md"
        entry = [f"## {wf['process']['version']} ({date.today().isoformat()}, status {wf['process']['status']})", ""]
        entry += [f"- {r}" for r in reasons] + [f"- Source: FigJam section `{wf['process']['source']['figma_page_or_section']}`, exported {wf['process']['source']['exported_at']}", ""]
        body = cl.read_text(encoding="utf-8").split("\n", 2)[2] if cl.exists() else ""
        cl.write_text(f"# {wf['process']['id']} changelog\n\n" + "\n".join(entry) + "\n" + body, encoding="utf-8")
        p["page"].parent.mkdir(parents=True, exist_ok=True)
        p["page"].write_text(render.page(wf), encoding="utf-8")
        p["scenarios"].parent.mkdir(parents=True, exist_ok=True)
        p["scenarios"].write_text(render.scenarios(wf), encoding="utf-8")
        written = [prev_path, p["dir"] / "board.json", cl, p["page"], p["scenarios"]]
        verification.append("- Written: " + ", ".join(f"`{x.relative_to(core.REPO).as_posix()}`" for x in written))
        nav = (core.REPO / "mkdocs.yml").read_text(encoding="utf-8")
        rel_page = p["page"].relative_to(core.REPO / "docs").as_posix()
        verification.append(f"- MkDocs nav: `{rel_page}` " + ("present" if rel_page in nav else "**missing: add it to `nav` in mkdocs.yml or the strict build fails**"))

    text = report(res, board, vlines, verification)
    (Path(a.report).write_text(text, encoding="utf-8") if a.report else print(text))
    emit(a, outcome="accepted", process_id=wf["process"]["id"], area=wf["process"]["area"], version=wf["process"]["version"], bump=bump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
