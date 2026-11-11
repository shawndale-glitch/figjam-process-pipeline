"""Render the user guide for a procedure: one page with a Spanish and an English tab, numbered
steps with screenshots, the expected result of each step, the narrated video and the QA stamp.

Usage:
  python tooling/procedure_render.py procedures/procure-to-pay/P2P-03-P02/procedure.yaml
  python tooling/procedure_render.py --all              # every procedure, plus docs/procedures/index.md

Reads the last run from build/procedures/<id>/<lang>/ (tooling/procedure_run.py). Writes:
  docs/procedures/<area>/<id>.md                         the guide (committed)
  docs/procedures/<area>/img/<id>/<lang>/S<n>.png        screenshots (committed)
  docs/procedures/<area>/media/<id>-<lang>.mp4 / .vtt    video and captions (committed: the demo app is fictional)
Without a passing run the page still renders, marked as not verified and without images or video.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import procedure_core as pc  # noqa: E402
from workflow_core import REPO, load_yaml  # noqa: E402

DOCS = REPO / "docs" / "procedures"
L = {
    "es": {"tab": "Español", "role": "Rol", "system": "Sistema", "process": "Proceso", "source": "Fuente", "owner": "Responsable",
           "version": "Versión", "checked": "Última verificación", "steps": "Pasos", "video": "Vídeo", "expect": "Resultado esperado",
           "ok": "Verificado el {date} en {app}. Pasos correctos: {n}. Comprobaciones de datos correctas: {v}.",
           "fail": "La última ejecución falló en el paso {step}: {error}. La guía puede no coincidir con el sistema.",
           "none": "Sin verificar: este procedimiento aún no se ha ejecutado contra el sistema.",
           "demo": "Grabado en Paydesk, una aplicación de formación ficticia que hace las veces del sistema real.",
           "novideo": "Su navegador no puede reproducir este vídeo.", "draft": "Borrador",
           "before": "Antes de empezar: {links}. Este procedimiento empieza donde termina ese.",
           "heading": "Se abre «{x}».", "dialog": "Se abre la ventana «{x}».", "row": "La lista muestra «{x}»", "text": "Aparece el mensaje «{x}».",
           "value": "El campo «{x}» muestra «{v}».", "contains": " con «{v}».", "visible": "Se ve «{x}».",
           "index": "Procedimientos", "intro": "Guías paso a paso de tareas en el sistema, cada una con su vídeo narrado. Se generan desde `procedures/` y se verifican al ejecutarlas.",
           "col": ["Procedimiento", "Proceso", "Rol", "Estado"]},
    "en": {"tab": "English", "role": "Role", "system": "System", "process": "Process", "source": "Source", "owner": "Owner",
           "version": "Version", "checked": "Last verified", "steps": "Steps", "video": "Video", "expect": "Expected result",
           "ok": "Verified on {date} in {app}. Steps passed: {n}. Data checks passed: {v}.",
           "fail": "The last run failed at step {step}: {error}. The guide may not match the system.",
           "none": "Not verified: this procedure has not been run against the system yet.",
           "demo": "Recorded in Paydesk, a fictional training app that stands in for the real system.",
           "novideo": "Your browser can't play this video.", "draft": "Draft",
           "before": "Before you start: {links}. This procedure starts where that one ends.",
           "heading": "«{x}» opens.", "dialog": "The «{x}» window opens.", "row": "The list shows «{x}»", "text": "The message «{x}» appears.",
           "value": "The «{x}» field shows «{v}».", "contains": " with «{v}».", "visible": "«{x}» is shown.",
           "index": "Procedures", "intro": "Step-by-step guides to tasks in the system, each with its narrated video. Generated from `procedures/` and verified by running them.",
           "col": ["Procedure", "Process", "Role", "Status"]},
}

PLACEHOLDER = {
    "es": {"number": "nº de factura", "supplier": "proveedor", "amount": "importe", "cost_centre": "centro de coste"},
    "en": {"number": "invoice number", "supplier": "supplier", "amount": "amount", "cost_centre": "cost centre"},
}


def expected(exp: dict | None, lang: str, data: dict) -> str:
    if not exp:
        return ""
    t, s = exp["target"], L[lang]
    x = pc.resolve(t.get("name") or t.get("label") or t.get("text") or t.get("placeholder") or t.get("role"), lang, data)
    if "value" in exp:
        return s["value"].format(x=x, v=pc.resolve(exp["value"], lang, data))
    key = t.get("role") if t.get("role") in ("heading", "dialog", "row") else "text" if "text" in t else "visible"
    out = s[key].format(x=x)
    if "contains" in exp:
        out = out.rstrip(".") + s["contains"].format(v=pc.resolve(exp["contains"], lang, data))
    elif key == "row":
        out += "."
    return out


def srt_to_vtt(srt: Path, vtt: Path) -> None:
    body = srt.read_text(encoding="utf-8").replace(",", ".")
    vtt.write_text("WEBVTT\n\n" + body, encoding="utf-8")


def last_run(pid: str, lang: str) -> dict | None:
    f = REPO / "build" / "procedures" / pid / lang / "qa-report.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def render(spec_path: Path) -> Path:
    spec = load_yaml(spec_path)
    p = spec["procedure"]
    pid, area = p["id"], pc.area_of(p["process"]) or "_"
    page = DOCS / area / f"{pid}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    proc_page = REPO / "docs" / "processes" / area / f"{p['process']}.md"
    process = f"[{p['process']}](../../processes/{area}/{p['process']}.md)" if proc_page.exists() else f"{p['process']}"
    out = ["<!-- Generated by tooling/procedure_render.py from " + spec_path.resolve().relative_to(REPO).as_posix() + ". Do not edit; change the procedure and re-run. -->",
           "", f"# {pid}: " + " / ".join(p["title"][x] for x in pc.languages_for(spec)), ""]
    shutil.rmtree(DOCS / area / "img" / pid, ignore_errors=True)   # no stale screenshots from a language no longer recorded
    for old in (DOCS / area / "media").glob(f"{pid}-*.*"):
        old.unlink()
    for lang in pc.languages_for(spec):   # one tab per language the system is recorded in
        s, run = L[lang], last_run(pid, lang)
        passed = run and run["result"] == "PASS"
        # the run's fixture values are deleted after it: the guide names the field instead
        data = {k: PLACEHOLDER[lang] for k in (spec.get("fixtures") or {})}
        img_dir = DOCS / area / "img" / pid / lang
        shutil.rmtree(img_dir, ignore_errors=True)
        if passed:
            img_dir.mkdir(parents=True)
            src = REPO / "build" / "procedures" / pid / lang
            for st in spec["steps"]:
                if (src / f"{st['id']}.png").exists():
                    shutil.copy2(src / f"{st['id']}.png", img_dir / f"{st['id']}.png")
            media = DOCS / area / "media"
            media.mkdir(exist_ok=True)
            shutil.copy2(src / "video.mp4", media / f"{pid}-{lang}.mp4")
            srt_to_vtt(src / "subtitles.srt", media / f"{pid}-{lang}.vtt")
        tab = [f"## {p['title'][lang]}", "", p.get("summary", {}).get(lang, ""), ""]
        if p.get("starts_from"):   # the shared opening (e.g. open an invoice) is its own guide
            links = " → ".join(f"[{q['procedure']['id']}: {q['procedure']['title'].get(lang) or next(iter(q['procedure']['title'].values()))}]"
                               f"(../{pc.area_of(q['procedure']['process']) or '_'}/{q['procedure']['id']}.md)" for _, q in pc.opening(spec))
            tab += ['!!! tip ""', "    " + s["before"].format(links=links), ""]
        if p["system"] == "demo-app":
            tab += ['!!! info ""', f"    {s['demo']}", ""]
        if passed:
            tab += ['!!! success ""', "    " + s["ok"].format(date=run["started"][:10], app=run["app_version"], n=len(run["steps"]), v=len(run["verify"])), ""]
        elif run:
            bad = next((x for x in run["steps"] if x["status"] == "fail"), None) or next((x for x in run["verify"] if x["status"] == "fail"), {})
            tab += ['!!! failure ""', "    " + s["fail"].format(step=bad.get("id") or bad.get("field"), error=bad.get("error") or bad.get("found")), ""]
        else:
            tab += ['!!! warning ""', f"    {s['none']}", ""]
        status = s["draft"] if p["status"] == "draft" else p["status"]
        tab += [f"| {s['role']} | {s['system']} | {s['process']} | {s['owner']} | {s['version']} |", "|---|---|---|---|---|",
                f"| {p['role']} | {p['system']} | {process} | {p['owner']} | {p['version']} ({status}) |", "",
                f"{s['source']}: {p.get('source', '-')}", ""]
        if passed:
            tab += [f"### {s['video']}", "",
                    f'<video controls preload="metadata" width="100%" src="../media/{pid}-{lang}.mp4">'
                    f'<track kind="subtitles" srclang="{lang}" label="{s["tab"]}" src="../media/{pid}-{lang}.vtt" default>{s["novideo"]}</video>', ""]
        tab += [f"### {s['steps']}", ""]
        for n, st in enumerate(spec["steps"], 1):
            tab.append(f"{n}. {pc.resolve(st['say'], lang, data)}")
            exp = expected(st.get("expect"), lang, data)
            if exp:
                tab += ["", f"    *{s['expect']}:* {exp}"]
            if passed and (img_dir / f"{st['id']}.png").exists():
                tab += ["", f"    ![{st['id']}](img/{pid}/{lang}/{st['id']}.png)"]
            tab.append("")
        out.append(f'=== "{s["tab"]}"')
        out.append("")
        out += [("    " + line) if line else "" for line in tab]
        out.append("")
    page.write_text(re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n", encoding="utf-8")
    return page


def render_index(specs: list[Path]) -> Path:
    rows = []
    for sp in specs:
        p = load_yaml(sp)["procedure"]
        area = pc.area_of(p["process"]) or "_"
        rows.append((p, area))
    out = ["<!-- Generated by tooling/procedure_render.py --all. Do not edit. -->", "", "# Procedimientos / Procedures", ""]
    for lang in pc.LANGS:
        s = L[lang]
        tab = [s["intro"], "", "| " + " | ".join(s["col"]) + " |", "|---|---|---|---|"]
        for p, area in rows:
            run = last_run(p["id"], lang)
            state = (s["draft"] if p["status"] == "draft" else p["status"]) + (" · ✔" if run and run["result"] == "PASS" else " · ✖" if run else "")
            title = p["title"].get(lang) or next(iter(p["title"].values()))   # English-only systems still list in both tabs
            tab.append(f"| [{p['id']}: {title}]({area}/{p['id']}.md) | {p['process']} | {p['role']} | {state} |")
        out += [f'=== "{s["tab"]}"', ""] + [("    " + x) if x else "" for x in tab] + [""]
    f = DOCS / "index.md"
    f.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("specs", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    specs = pc.all_specs() if a.all or not a.specs else a.specs
    for sp in specs:
        print(f"wrote {render(sp).relative_to(REPO).as_posix()}")
    if a.all or not a.specs:
        print(f"wrote {render_index(pc.all_specs()).relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
