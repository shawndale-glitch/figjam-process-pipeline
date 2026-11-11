"""Shared logic for procedures: one task done in a system, turned into a guide, a narrated
video per language and a QA run.

Rules live in governance/workflow-rules.yaml -> procedure; the contract is
schemas/procedure.schema.json. Findings use the same shape as the workflow linter.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from workflow_core import REPO, Finding, areas, load_yaml

LANGS = ("es", "en")
TEMPLATE = re.compile(r"\{\{([a-z_]+)\.([a-z_]+)\}\}")
SHORT_TEXT = re.compile(r"^[\w:.,\-/ ()]{1,40}$")   # amounts, times, codes, a short neutral remark
PERSONAL = [  # simplified from governance/sensitive-data.yaml; the full scan still runs in CI
    ("an e-mail address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("a phone number", re.compile(r"\+?\d[\d ]{8,}\d")),
    ("a DNI/NIE", re.compile(r"\b[XYZ]?\d{7,8}[A-Z]\b")),
]
FIXTURE_PERSON = re.compile(r"^(Test|Prueba|Demo)\b")
LOCATOR_KEYS = {"role", "name", "label", "placeholder", "text", "within"}   # within: a container the user sees, e.g. a dialog


def rules() -> dict:
    return load_yaml(REPO / "governance" / "workflow-rules.yaml")["procedure"]


def languages_for(spec: dict) -> list[str]:
    """Languages a procedure must have and is recorded in: the system's own list, else the procedure default."""
    cfg = rules()
    system = cfg.get("systems", {}).get(spec.get("procedure", {}).get("system"), {})
    return list(system.get("languages") or cfg.get("languages") or LANGS)


def find_procedure(pid: str) -> tuple[Path, dict] | None:
    """The procedure.yaml with this id, wherever it sits under procedures/."""
    for path in all_specs():
        spec = load_yaml(path)
        if spec.get("procedure", {}).get("id") == pid:
            return path, spec
    return None


def opening(spec: dict) -> list[tuple[Path, dict]]:
    """The procedures that run before this one (starts_from, then its own starts_from...), first one first."""
    chain, seen, cur = [], {spec.get("procedure", {}).get("id")}, spec.get("procedure", {}).get("starts_from")
    while cur:
        if cur in seen:
            raise ValueError(f"starts_from loops back to {cur}")
        found = find_procedure(cur)
        if not found:
            raise ValueError(f"starts_from names {cur}, which is not in procedures/")
        chain.insert(0, found)
        seen.add(cur)
        cur = found[1]["procedure"].get("starts_from")
    return chain


def schema_errors(spec: dict) -> list[str]:
    import jsonschema
    schema = json.loads((REPO / "schemas" / "procedure.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in v.iter_errors(spec)]


def area_of(process_id: str) -> str | None:
    return areas().get(process_id.split("-")[0])


def find_workflow(process_id: str) -> dict | None:
    area = area_of(process_id)
    path = REPO / "workflows" / (area or "_") / process_id / "workflow.yaml"
    return load_yaml(path) if path.exists() else None


def texts(spec: dict):
    """Every bilingual text in the file, with where it sits."""
    p = spec.get("procedure", {})
    for key in ("title", "summary"):
        if key in p:
            yield f"procedure.{key}", p[key]
    for st in spec.get("steps", []):
        yield f"{st.get('id')}.say", st.get("say")
        for part in ("do", "expect"):
            tgt = (st.get(part) or {}).get("target") or {}
            for k in ("name", "label", "placeholder", "text"):
                if isinstance(tgt.get(k), dict):
                    yield f"{st.get('id')}.{part}.{k}", tgt[k]
            if isinstance((tgt.get("within") or {}).get("name"), dict):
                yield f"{st.get('id')}.{part}.within", tgt["within"]["name"]
        if isinstance((st.get("expect") or {}).get("contains"), dict):
            yield f"{st.get('id')}.expect.contains", st["expect"]["contains"]


def lint(spec: dict) -> list[Finding]:
    f: list[Finding] = []
    add = lambda rule, sev, node, msg: f.append(Finding(rule, sev, node, node or "", msg))
    for e in schema_errors(spec):
        add("P1", "error", None, e)
    p = spec.get("procedure", {})
    cfg = rules()

    # P2: never production
    if p.get("environment") not in ("test", "training"):
        add("P2", "error", "procedure.environment", f"environment is {p.get('environment')!r}; use test or training")
    blob = json.dumps(spec, ensure_ascii=False).lower()
    if re.search(r"\bprod(uction|uccion|ucción)?\b", blob):
        add("P2", "error", None, "the file mentions production; procedures run only against test or training")

    # P3: every language the system is recorded in, nothing left as TODO
    langs = languages_for(spec)
    for where, t in texts(spec):
        for lang in langs:
            val = (t or {}).get(lang, "") if isinstance(t, dict) else ""
            if not val.strip() or "TODO" in val:
                add("P3", "error", where, f"missing {lang.upper()} text" if not val.strip() else f"{lang.upper()} text still says TODO")

    steps = spec.get("steps", [])
    for i, st in enumerate(steps):
        sid = st.get("id", f"#{i + 1}")
        do = st.get("do") or {}
        # P4: a check on every step except an opening navigation
        if not st.get("expect") and not (i == 0 and do.get("action") == "open"):
            add("P4", "error", sid, "step has no expected result")
        # P5: locators by what the user sees
        for part in ("do", "expect"):
            tgt = (st.get(part) or {}).get("target")
            if tgt is None:
                continue
            extra = set(tgt) - LOCATOR_KEYS
            if extra:
                add("P5", "error", f"{sid}.{part}", f"locator uses {', '.join(sorted(extra))}; use role + name, label, placeholder or text")
            if "name" in tgt and "role" not in tgt:
                add("P5", "error", f"{sid}.{part}", "name needs a role (button, link, row, heading...)")
        if do.get("action") in ("click", "fill", "select") and not do.get("target"):
            add("P5", "error", sid, f"{do.get('action')} has no target")
        # P7: typed values
        val = do.get("value")
        for v in (val.values() if isinstance(val, dict) else [val] if isinstance(val, str) else []):
            if TEMPLATE.fullmatch(v):
                continue
            if not SHORT_TEXT.fullmatch(v):
                add("P7", "error", sid, f"typed value {v!r} is not a fixture reference, a code or short neutral text")
            for what, rx in PERSONAL:
                if rx.search(v):
                    add("P7", "error", sid, f"typed value looks like {what}")
        if isinstance(val, dict):
            for lang in langs:
                if not val.get(lang, "").strip():
                    add("P3", "error", f"{sid}.do.value", f"missing {lang.upper()} text")
        for ref in TEMPLATE.findall(json.dumps(st, ensure_ascii=False)):
            if ref[0] not in (spec.get("fixtures") or {}):
                add("P1", "error", sid, f"{{{{{ref[0]}.{ref[1]}}}}} refers to a fixture that isn't defined")
    for name, fx in (spec.get("fixtures") or {}).items():
        for k, v in fx.items():
            if k in ("supplier", "customer", "name", "first_name", "last_name") and isinstance(v, str) and not FIXTURE_PERSON.match(v):
                add("P7", "error", f"fixtures.{name}.{k}", f"fixture party {v!r} must start with Test, Prueba or Demo")
            if isinstance(v, str) and any(rx.search(v) for _, rx in PERSONAL):
                add("P7", "error", f"fixtures.{name}.{k}", "fixture value looks like personal data")

    # P8 / P6 / PW2: tie to the process board
    if p.get("system") and p["system"] not in cfg["systems"]:
        add("P8", "error", "procedure.system", f"system {p['system']!r} is not in procedure.systems")
    if p.get("process"):
        wf = find_workflow(p["process"])
        if wf is None:
            add("PW2", "warning", "procedure.process", f"{p['process']} is not in workflows/ yet; role and step_ref were not checked")
        else:
            lanes = {l["role"] for l in wf.get("lanes", [])}
            if p.get("role") not in lanes:
                add("P6", "error", "procedure.role", f"role {p.get('role')!r} is not a lane on {p['process']} ({', '.join(sorted(lanes))})")
            tasks = {n["id"]: n for n in wf.get("nodes", []) if n.get("type") in ("task", "subprocess")}
            ref = p.get("step_ref", "")
            if ref not in tasks and ref not in {n.get("label") for n in tasks.values()}:
                add("P8", "error", "procedure.step_ref", f"{ref!r} is not a task on {p['process']}")

    # P9: the procedure this one starts from
    if p.get("starts_from"):
        try:
            for path, pre in opening(spec):
                pp = pre["procedure"]
                if pp.get("system") != p.get("system"):
                    add("P9", "error", "procedure.starts_from", f"{pp['id']} runs on {pp.get('system')}, this one on {p.get('system')}")
                missing = sorted(set(pre.get("fixtures") or {}) - set(spec.get("fixtures") or {}))
                if missing:
                    add("P9", "error", "fixtures", f"{pp['id']} uses fixture(s) {', '.join(missing)}; declare them here too")
        except ValueError as e:
            add("P9", "error", "procedure.starts_from", str(e))

    if len(steps) > cfg["max_steps"]:
        add("PW1", "warning", None, f"{len(steps)} steps; split procedures longer than {cfg['max_steps']}")
    return f


def resolve(value, lang: str, data: dict):
    """A bilingual or templated value -> the text for one language with fixtures filled in."""
    if isinstance(value, dict):
        value = value.get(lang, "")
    if not isinstance(value, str):
        return value
    return TEMPLATE.sub(lambda m: str(data.get(m[1], {}).get(m[2], m[0])), value)


def all_specs() -> list[Path]:
    return sorted((REPO / "procedures").glob("*/*/procedure.yaml"))
