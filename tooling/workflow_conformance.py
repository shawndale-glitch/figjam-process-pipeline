"""Conformance checks for an application (consumer) against a released workflow.

Called by .github/workflows/workflow-conformance.yml (a reusable workflow that runs in the
consumer's repository). Rules: governance/workflow-rules.yaml -> conformance.

  resolve  Pick the newest release tag <ID>@<semver> that satisfies a range.
           python workflow_conformance.py resolve --process P2P-03 --range ^1.0.0 --docs-repo owner/figjam-process-pipeline

  check    C1 traceability + C4 manual evidence for the happy path.
           python workflow_conformance.py check --model workflow.yaml --bindings conformance/P2P-03/bindings.yaml \
               --range ^1.0.0 --openapi "api/**/*.yaml" --asyncapi "events/**/*.yaml" --report conformance-report.md

C2 (scenarios) runs the consumer's own BDD runner against the generated scenarios.feature; the
reusable workflow takes that command as an input. C3 (runtime) is scheduled separately.
Exit codes: 0 pass, 1 fail, 2 usage error.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow_render import paths_through  # noqa: E402

BINDABLE = {"event.start", "event.intermediate", "event.end", "task", "subprocess", "gateway.xor"}
KINDS = {"api-operation", "event", "vendor-config", "manual-step"}


# ---------------------------------------------------------------- semver ranges

def sv(s: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", s.strip())
    if not m:
        raise ValueError(f"not a version: {s}")
    return int(m[1]), int(m[2]), int(m[3])


def satisfies(version: str, rng: str) -> bool:
    """Supports exact (1.2.3), caret (^1.2.3), tilde (~1.2.3) and space-separated comparators (>=1.0.0 <2.0.0)."""
    v = sv(version)
    rng = rng.strip()
    if rng.startswith("^"):
        b = sv(rng[1:])
        upper = (b[0] + 1, 0, 0) if b[0] > 0 else ((0, b[1] + 1, 0) if b[1] > 0 else (0, 0, b[2] + 1))
        return b <= v < upper
    if rng.startswith("~"):
        b = sv(rng[1:])
        return b <= v < (b[0], b[1] + 1, 0)
    ok = True
    for part in rng.split():
        m = re.fullmatch(r"(>=|<=|>|<|=)?(.+)", part)
        op, target = m[1] or "=", sv(m[2])
        ok &= {"=": v == target, ">=": v >= target, "<=": v <= target, ">": v > target, "<": v < target}[op]
    return ok


# ---------------------------------------------------------------- resolve

def cmd_resolve(a) -> int:
    out = subprocess.run(["gh", "release", "list", "-R", a.docs_repo, "--limit", "200", "--json", "tagName"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        return 1
    tags = [r["tagName"] for r in json.loads(out.stdout or "[]")]
    cands = []
    for t in tags:
        if t.startswith(f"{a.process}@"):
            ver = t.split("@", 1)[1]
            try:
                if satisfies(ver, a.range):
                    cands.append((sv(ver), t))
            except ValueError:
                pass
    if not cands:
        print(f"No release of {a.process} satisfies {a.range}", file=sys.stderr)
        return 1
    tag = max(cands)[1]
    print(tag)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"tag={tag}\nversion={tag.split('@', 1)[1]}\n")
    return 0


# ---------------------------------------------------------------- spec indexes

def _load(path: str):
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text) if path.endswith(".json") else yaml.safe_load(text)


def openapi_operations(patterns: list[str]) -> set[str]:
    ops = set()
    for pat in patterns:
        for f in glob.glob(pat, recursive=True):
            doc = _load(f) or {}
            for item in (doc.get("paths") or {}).values():
                for op in (item or {}).values():
                    if isinstance(op, dict) and op.get("operationId"):
                        ops.add(op["operationId"])
    return ops


def asyncapi_events(patterns: list[str]) -> set[str]:
    names = set()

    def collect(node):
        if isinstance(node, dict):
            for k in ("name", "messageId", "title"):
                if isinstance(node.get(k), str):
                    names.add(node[k])
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    for pat in patterns:
        for f in glob.glob(pat, recursive=True):
            doc = _load(f) or {}
            names.update((doc.get("channels") or {}).keys())
            names.update(((doc.get("components") or {}).get("messages") or {}).keys())
            collect(doc.get("components", {}).get("messages", {}))
            collect(doc.get("channels", {}))
    return names


# ---------------------------------------------------------------- check

def tbc(v) -> bool:
    return v is None or (isinstance(v, str) and (not v.strip() or "TBC" in v))


def cmd_check(a) -> int:
    wf = yaml.safe_load(Path(a.model).read_text(encoding="utf-8"))
    p = wf["process"]
    bpath = Path(a.bindings)
    b = yaml.safe_load(bpath.read_text(encoding="utf-8")) if bpath.exists() else None
    ops = openapi_operations(a.openapi)
    evs = asyncapi_events(a.asyncapi)
    by = {n["id"]: n for n in wf["nodes"]}
    exits = {}
    for f in wf["flows"]:
        if f["type"] == "sequence" and f.get("condition"):
            exits.setdefault(f["from"], []).append(f["condition"])

    c1, c4, info = [], [], []
    fail = lambda lst, nid, msg: lst.append((nid, msg))

    if not satisfies(p["version"], a.range):
        fail(c1, None, f"Model version {p['version']} does not satisfy the pinned range {a.range}")
    if p["status"] != "validated":
        fail(c1, None, f"Model status is `{p['status']}`; only validated releases can be implemented")
    if b is None:
        fail(c1, None, f"No bindings file at {bpath}")
        b = {"bindings": []}
    else:
        if b.get("process") != p["id"]:
            fail(c1, None, f"Bindings are for process {b.get('process')}, model is {p['id']}")
        if b.get("process_version") and not satisfies(str(b["process_version"]), a.range):
            fail(c1, None, f"Bindings were written for {b['process_version']}, outside {a.range}")

    binds = {}
    for x in b.get("bindings", []):
        binds.setdefault(str(x.get("node")), []).append(x)
    for nid in binds:
        if nid not in by:
            fail(c1, nid, "Binding points at a node that isn't in the model (stale binding?)")

    happy = [nid for nid, _ in paths_through(wf)[0]]
    for nid in happy:
        n = by[nid]
        if n["type"] not in BINDABLE:
            continue
        lbl = f"{n['type']} «{n['label']}»"
        if nid not in binds:
            fail(c1, nid, f"{lbl}: no binding")
            continue
        for x in binds[nid]:
            k = x.get("kind")
            if k not in KINDS:
                fail(c1, nid, f"{lbl}: unknown binding kind `{k}`")
            elif k == "api-operation":
                if tbc(x.get("operation_id")):
                    fail(c1, nid, f"{lbl}: operation_id is TBC")
                elif not ops:
                    fail(c1, nid, f"{lbl}: no OpenAPI spec given, can't resolve `{x['operation_id']}`")
                elif x["operation_id"] not in ops:
                    fail(c1, nid, f"{lbl}: operationId `{x['operation_id']}` not found in the OpenAPI specs")
            elif k == "event":
                if tbc(x.get("event")):
                    fail(c1, nid, f"{lbl}: event is TBC")
                elif not evs:
                    fail(c1, nid, f"{lbl}: no AsyncAPI spec given, can't resolve `{x['event']}`")
                elif x["event"] not in evs:
                    fail(c1, nid, f"{lbl}: event `{x['event']}` not found in the AsyncAPI specs")
            elif k in ("vendor-config", "manual-step"):
                if k == "vendor-config" and tbc(x.get("config_key")):
                    fail(c1, nid, f"{lbl}: config_key is TBC")
                ev = x.get("evidence")
                if not isinstance(ev, dict) or any(tbc(ev.get(f)) for f in ("role", "date", "link")):
                    fail(c4, nid, f"{lbl}: needs evidence {{role, date, link}} (UAT sign-off)")
        if n["type"] == "gateway.xor":
            conds = {}
            for x in binds[nid]:
                conds.update(x.get("conditions") or {})
            missing = [c for c in exits.get(nid, []) if tbc(conds.get(c))]
            if missing:
                fail(c1, nid, f"{lbl}: no implementation mapped for exit(s) {missing}")

    bound = {nid for nid in binds if nid in by}
    flow_nodes = [n for n in wf["nodes"] if n["type"] in BINDABLE]
    for n in flow_nodes:
        if n["id"] not in happy and n["id"] not in bound:
            info.append((n["id"], f"{n['type']} «{n['label']}» is off the happy path and unbound (C2 non-happy scenarios will cover it)"))
    cov = f"{len(bound & {n['id'] for n in flow_nodes})}/{len(flow_nodes)}"

    ok = not c1 and not c4
    L = [f"# Conformance: {p['id']} {p['version']} (range {a.range})", "",
         "| Layer | Result |", "|---|---|",
         f"| C1 traceability | {'✅ pass' if not c1 else f'❌ {len(c1)} issue(s)'} |",
         f"| C4 manual evidence | {'✅ pass' if not c4 else f'❌ {len(c4)} issue(s)'} |",
         f"| Node coverage (bound / bindable) | {cov} |", ""]
    for title, items in (("C1 issues", c1), ("C4 issues", c4), ("Info", info)):
        if items:
            L += [f"## {title}", ""] + [f"- {'`' + nid + '` ' if nid else ''}{m}" for nid, m in items] + [""]
    text = "\n".join(L)
    print(text)
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps({"process": p["id"], "version": p["version"], "range": a.range, "c1": not c1, "c4": not c4,
                                            "coverage": cov, "issues": [m for _, m in c1 + c4]}, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--process", required=True)
    r.add_argument("--range", required=True)
    r.add_argument("--docs-repo", required=True)
    c = sub.add_parser("check")
    c.add_argument("--model", required=True)
    c.add_argument("--bindings", required=True)
    c.add_argument("--range", required=True)
    c.add_argument("--openapi", nargs="*", default=[])
    c.add_argument("--asyncapi", nargs="*", default=[])
    c.add_argument("--report")
    c.add_argument("--json")
    a = ap.parse_args()
    return cmd_resolve(a) if a.cmd == "resolve" else cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
