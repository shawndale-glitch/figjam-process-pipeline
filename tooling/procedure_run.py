"""Run a procedure against its system, record it and produce the narrated video, subtitles,
step screenshots and QA report, once per language.

Usage:
  python tooling/procedure_run.py procedures/procure-to-pay/P2P-03-P02/procedure.yaml --start-demo
  python tooling/procedure_run.py <procedure.yaml> --lang es --voice none --headed
  BASE_URL_ENV=<entry URL> python tooling/procedure_run.py --login <system>   # a person signs in once; session kept in .auth/
  PW_CHANNEL=chrome python tooling/procedure_run.py ...   # use the installed Chrome where policy blocks Playwright's Chromium

What happens, per language:
  1. Fixtures (fictional records) are created through the system's API.
  2. Each step's `say` text becomes speech (voice engine: sapi on Windows, piper on Linux, or none).
  3. Playwright opens the screens in that language, shows a caption, highlights the control, acts,
     and checks the expected result. The narration sets the pace: a step lasts as long as its audio.
  4. The API confirms the data was saved (`verify`) and the fixtures are deleted.
  5. ffmpeg joins the recording and the narration into a 1080p MP4 with a subtitle track.
A video is kept only when every step and every verify passed. Otherwise the report names the step.

Output: build/procedures/<id>/<lang>/  video.mp4, subtitles.srt, S<n>.png, qa-report.json, qa-report.md
Needs: pip install -r requirements-media.txt && python -m playwright install chromium
Exit codes: 0 = every language passed, 1 = a step or verify failed, 2 = setup error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import procedure_core as pc  # noqa: E402
from workflow_core import REPO, load_yaml  # noqa: E402

VIEWPORT = {"width": 1280, "height": 720}
CULTURE = {"es": "es-ES", "en": "en-US"}
HIGHLIGHT, PASSED = "#f29d38", "#2fa36b"
LEAD_IN, PAUSE, HOLD = 0.7, 0.45, 1.2   # seconds: highlight before acting, gap after narration, last frame

OVERLAY_JS = r"""
(() => {
  if (window.__proc) return;
  const make = id => {
    const el = document.createElement('div');
    el.id = id; el.setAttribute('popover', 'manual');
    Object.assign(el.style, { position: 'fixed', inset: 'auto', margin: '0', border: '0', pointerEvents: 'none', overflow: 'visible' });
    document.documentElement.appendChild(el);
    return el;
  };
  const front = el => { try { el.hidePopover(); } catch (e) {} try { el.showPopover(); } catch (e) {} };
  window.__proc = {
    caption(text, n, total) {
      const el = document.getElementById('__proc_cap') || make('__proc_cap');
      Object.assign(el.style, { left: '50%', bottom: '26px', transform: 'translateX(-50%)', maxWidth: '82%', padding: '12px 22px',
        background: 'rgba(14,22,30,.88)', color: '#fff', font: '600 22px/1.35 "Segoe UI", Arial, sans-serif', borderRadius: '10px',
        textAlign: 'center', boxShadow: '0 6px 20px rgba(0,0,0,.25)' });
      el.innerHTML = '';
      const b = document.createElement('span');
      b.textContent = n + '/' + total;
      Object.assign(b.style, { display: 'inline-block', marginRight: '12px', padding: '1px 9px', borderRadius: '999px', background: '#f29d38', color: '#14202b', fontSize: '17px', verticalAlign: '2px' });
      el.append(b, document.createTextNode(text));
      front(el);
    },
    hideCaption() { const el = document.getElementById('__proc_cap'); if (el) try { el.hidePopover(); } catch (e) {} },
    box(r, color) {
      const el = document.getElementById('__proc_box') || make('__proc_box');
      Object.assign(el.style, { left: (r.x - 6) + 'px', top: (r.y - 6) + 'px', width: (r.width + 12) + 'px', height: (r.height + 12) + 'px',
        padding: '0', background: 'transparent', border: '3px solid ' + color, borderRadius: '8px', boxShadow: '0 0 0 4px ' + color + '33' });
      front(el);
      const cap = document.getElementById('__proc_cap'); if (cap && cap.matches(':popover-open')) front(cap);
    },
    clearBox() { const el = document.getElementById('__proc_box'); if (el) try { el.hidePopover(); } catch (e) {} },
  };
})();
"""


class StepFailed(Exception):
    pass


# ---------------------------------------------------------------- system adapters

class DemoApi:
    """Paydesk's JSON API (examples/procedure-demo): plays the part of a real system's API."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _call(self, method: str, path: str, body=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")

    def version(self) -> str:
        v = self._call("GET", "/api/version")
        return f"{v['app']} {v['version']}"

    def create(self, name: str, fixture: dict) -> dict:
        return self._call("POST", "/api/invoices", fixture)

    def get(self, record: dict) -> dict:
        return self._call("GET", f"/api/invoices/{record['number']}")

    def delete(self, record: dict) -> None:
        try:
            self._call("DELETE", f"/api/invoices/{record['number']}")
        except urllib.error.HTTPError:
            pass

    def url(self, path: str, lang: str) -> str:
        return f"{self.base}{path}{'&' if '?' in path else '?'}lang={lang}"


# A real system plugs in here with the same five methods: create/get/delete the fixture records
# through the system's own API, url() for its screens and version() for the QA report. Credentials
# come from the environment or a git-ignored file, never from the repository.
ADAPTERS = {"demo": DemoApi}


def system_for(spec: dict):
    return system_named(spec["procedure"]["system"])


def session_file(name: str) -> Path:
    return REPO / ".auth" / f"{name}.json"


def system_named(name: str):
    cfg = pc.rules()["systems"][name]
    base = os.environ.get(cfg["base_url_env"]) or cfg.get("base_url_default")
    if not base:
        raise SystemExit(f"{name}: set {cfg['base_url_env']}")
    return ADAPTERS[cfg["api"]](base)


def ensure_demo(api: DemoApi) -> subprocess.Popen | None:
    try:
        api.version()
        return None
    except (urllib.error.URLError, OSError):
        port = api.base.rsplit(":", 1)[-1]
        proc = subprocess.Popen([sys.executable, str(REPO / "examples" / "procedure-demo" / "app" / "server.py"), "--port", port],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            time.sleep(0.1)
            try:
                api.version()
                return proc
            except (urllib.error.URLError, OSError):
                pass
        proc.kill()
        raise SystemExit(f"Paydesk did not start on {api.base}")


# ---------------------------------------------------------------- voice

def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


def speak(clips: list[tuple[str, Path]], lang: str, engine: str) -> dict[Path, float]:
    """Write one WAV per (text, path); return each clip's length in seconds (estimated for engine 'none')."""
    if engine == "none":
        return {p: max(1.6, len(text.split()) / 2.6 + 0.4) for text, p in clips}
    if engine == "sapi":
        job = [{"text": t, "path": str(p), "culture": CULTURE[lang]} for t, p in clips]
        with tempfile.TemporaryDirectory() as tmp:
            jf, ps = Path(tmp) / "job.json", Path(tmp) / "say.ps1"
            jf.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            ps.write_text(
                "Add-Type -AssemblyName System.Speech\n"
                f"$job = Get-Content -Raw -Encoding UTF8 '{jf}' | ConvertFrom-Json\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "foreach ($c in $job) {\n"
                "  $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq $c.culture } | Select-Object -First 1\n"
                "  if (-not $v) { Write-Error ('No ' + $c.culture + ' voice installed'); exit 3 }\n"
                "  $s.SelectVoice($v.VoiceInfo.Name); $s.Rate = 0\n"
                "  $s.SetOutputToWaveFile($c.path); $s.Speak($c.text); $s.SetOutputToNull()\n"
                "}\n", encoding="utf-8-sig")
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"sapi voice failed: {r.stderr.strip()}")
    elif engine == "piper":
        model = os.environ.get(f"PIPER_MODEL_{lang.upper()}")
        if not model:
            raise SystemExit(f"piper: set PIPER_MODEL_{lang.upper()} to a .onnx voice model")
        for text, p in clips:
            subprocess.run(["piper", "--model", model, "--output_file", str(p)], input=text, text=True, check=True, capture_output=True)
    else:
        raise SystemExit(f"unknown voice engine {engine!r}")
    return {p: wav_seconds(p) for _, p in clips}


# ---------------------------------------------------------------- browser

def locate(page, target: dict, lang: str, data: dict):
    """Find a control the way a user would: role + name, label, placeholder or text."""
    val = lambda k: pc.resolve(target[k], lang, data)
    # bilingual UI text matches exactly; data values, and rows or list items (named after all their cells), match by containment
    exact = lambda k: isinstance(target[k], dict) and target.get("role") not in ("row", "listitem")
    if "within" in target:   # only inside a container the user sees, e.g. the dialog that is open
        w = target["within"]
        page = page.get_by_role(w["role"], name=pc.resolve(w["name"], lang, data), exact=isinstance(w["name"], dict)).first
    if "role" in target:
        if "name" in target:
            return page.get_by_role(target["role"], name=val("name"), exact=exact("name"))
        return page.get_by_role(target["role"])
    for k, fn in (("label", page.get_by_label), ("placeholder", page.get_by_placeholder), ("text", page.get_by_text)):
        if k in target:
            return fn(val(k), exact=exact(k))
    raise StepFailed(f"no usable locator in {target}")


def describe(target: dict, lang: str, data: dict) -> str:
    words = [f"{k} \"{pc.resolve(v, lang, data)}\"" if k != "role" else v for k, v in target.items() if k != "within"]
    if "within" in target:
        words.append(f"in {target['within']['role']} \"{pc.resolve(target['within']['name'], lang, data)}\"")
    return " ".join(words)


BROWSER_CHANNEL = os.environ.get("PW_CHANNEL") or None   # e.g. "chrome": the installed, signed Chrome, where policy blocks Playwright's own Chromium
STEP_TIMEOUT_S = 8   # per system: rules systems.<name>.step_timeout_s (large web apps are slower than the demo app)


def wait_visible(loc, target: dict, lang: str, data: dict) -> None:
    try:
        loc.wait_for(state="visible", timeout=STEP_TIMEOUT_S * 1000)
    except Exception:
        raise StepFailed(f"could not find {describe(target, lang, data)} on screen within {STEP_TIMEOUT_S} s") from None


def mark(page, loc, color: str) -> None:
    loc.scroll_into_view_if_needed(timeout=5000)
    box = loc.bounding_box()
    if box:
        page.evaluate("r => window.__proc.box(r, %s)" % json.dumps(color), box)


def act(page, api, step: dict, lang: str, data: dict) -> None:
    do = step["do"]
    if do["action"] == "open":
        page.goto(api.url(do.get("path", "/"), lang))
        try:   # single-page apps wire up their menus after the first paint
            page.wait_for_load_state("networkidle", timeout=STEP_TIMEOUT_S * 1000)
        except Exception:  # noqa: BLE001 - a page that keeps polling never goes idle; the step's own check still applies
            pass
        return
    loc = locate(page, do["target"], lang, data).first
    wait_visible(loc, do["target"], lang, data)
    value = pc.resolve(do.get("value"), lang, data)
    if do["action"] == "click":
        loc.click()
    elif do["action"] == "select":
        loc.select_option(value)
    elif do["action"] == "press":
        loc.press(do["key"])
    elif do["action"] == "fill":
        kind = (loc.get_attribute("type") or "").lower()
        if kind in ("date", "time", "datetime-local", "month"):
            loc.fill(value)
        else:
            loc.fill("")
            loc.press_sequentially(value, delay=45)


def check(page, step: dict, lang: str, data: dict):
    exp = step.get("expect")
    if not exp:
        return None
    loc = locate(page, exp["target"], lang, data).first
    try:
        loc.wait_for(state="visible" if exp.get("visible", True) else "hidden", timeout=STEP_TIMEOUT_S * 1000)
    except Exception:
        raise StepFailed(f"expected {describe(exp['target'], lang, data)} to be {'visible' if exp.get('visible', True) else 'hidden'}") from None
    if "contains" in exp:
        want = pc.resolve(exp["contains"], lang, data)
        got = loc.inner_text()
        if want not in got:
            raise StepFailed(f"expected text {want!r}, found {got!r}")
    if "value" in exp:
        want = pc.resolve(exp["value"], lang, data)
        got = loc.input_value()
        if got != want:
            raise StepFailed(f"expected value {want!r}, found {got!r}")
    return loc if exp.get("visible", True) else None   # nothing on screen to highlight once it has gone


# ---------------------------------------------------------------- one language

def srt_time(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def run_lang(spec: dict, api, lang: str, voice: str, out: Path, headed: bool) -> dict:
    from playwright.sync_api import sync_playwright

    shutil.rmtree(out, ignore_errors=True)
    (out / "audio").mkdir(parents=True)
    p = spec["procedure"]
    report = {"procedure": p["id"], "version": p["version"], "lang": lang, "system": p["system"], "app_version": api.version(),
              "voice": voice, "rules_version": load_yaml(REPO / "governance" / "workflow-rules.yaml")["rules_version"],
              "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "steps": [], "verify": [], "result": "FAIL"}
    created: dict[str, dict] = {}
    try:
        for name, fx in (spec.get("fixtures") or {}).items():
            created[name] = api.create(name, fx)
        data = created
        steps = spec["steps"]
        clips = [(pc.resolve(st["say"], lang, data), out / "audio" / f"{st['id']}.wav") for st in steps]
        lengths = speak(clips, lang, voice)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not headed, channel=BROWSER_CHANNEL)
            state = session_file(p["system"])
            ctx = browser.new_context(viewport=VIEWPORT, record_video_dir=str(out / "raw"), record_video_size=VIEWPORT, locale=CULTURE[lang],
                                      storage_state=str(state) if state.exists() else None)
            ctx.add_init_script(OVERLAY_JS)
            page = ctx.new_page()
            t0 = time.monotonic()
            page.goto("about:blank")
            failed = None
            # starts_from: do the opening procedure(s) first, without captions or narration, then cut them from the video
            for path, pre in pc.opening(spec):
                report["opening"] = report.get("opening", []) + [pre["procedure"]["id"]]
                for st in pre["steps"]:
                    try:
                        if st["do"]["action"] != "open":
                            wait_visible(locate(page, st["do"]["target"], lang, data).first, st["do"]["target"], lang, data)
                        act(page, api, st, lang, data)
                        check(page, st, lang, data)
                    except Exception as e:  # noqa: BLE001
                        failed = {"id": f"{pre['procedure']['id']}.{st['id']}", "say": "", "start": 0, "end": 0, "status": "fail",
                                  "error": f"opening step failed: {str(e).splitlines()[0][:280]}"}
                        page.screenshot(path=str(out / "opening-fail.png"))
                        report["steps"].append(failed)
                        break
                if failed:
                    break
            trim = time.monotonic() - t0
            t0 = time.monotonic()
            for i, st in enumerate(steps):
                if failed:
                    break
                text, audio = clips[i]
                start = time.monotonic() - t0
                row = {"id": st["id"], "say": text, "start": round(start, 2), "status": "pass"}
                try:
                    if st["do"]["action"] != "open":
                        page.evaluate("([t,n,m]) => window.__proc.caption(t,n,m)", [text, i + 1, len(steps)])
                        loc = locate(page, st["do"]["target"], lang, data).first
                        wait_visible(loc, st["do"]["target"], lang, data)
                        mark(page, loc, HIGHLIGHT)
                        time.sleep(LEAD_IN)
                        if st["do"]["action"] in ("click", "press"):
                            page.evaluate("() => window.__proc.hideCaption()")
                            page.screenshot(path=str(out / f"{st['id']}.png"))
                            page.evaluate("([t,n,m]) => window.__proc.caption(t,n,m)", [text, i + 1, len(steps)])
                    act(page, api, st, lang, data)
                    page.evaluate("() => window.__proc.clearBox()")
                    page.evaluate("([t,n,m]) => window.__proc.caption(t,n,m)", [text, i + 1, len(steps)])
                    seen = check(page, st, lang, data)
                    if seen is not None:
                        mark(page, seen, PASSED)
                    if not (out / f"{st['id']}.png").exists():
                        page.evaluate("() => window.__proc.hideCaption()")
                        page.screenshot(path=str(out / f"{st['id']}.png"))
                        page.evaluate("([t,n,m]) => window.__proc.caption(t,n,m)", [text, i + 1, len(steps)])
                except Exception as e:  # noqa: BLE001 - any failure is a QA finding on this step
                    row.update(status="fail", error=str(e).splitlines()[0][:300])
                    page.screenshot(path=str(out / f"{st['id']}-fail.png"))
                    failed = row
                rest = lengths[audio] + PAUSE - (time.monotonic() - t0 - start)
                if rest > 0 and not failed:
                    time.sleep(rest)
                page.evaluate("() => window.__proc && window.__proc.clearBox()")
                row["end"] = round(time.monotonic() - t0, 2)
                report["steps"].append(row)
                if failed:
                    break
            time.sleep(HOLD)
            raw = Path(page.video.path())
            ctx.close()
            browser.close()

        if not failed:
            for v in spec.get("verify") or []:
                rec = api.get(created[v["fixture"]])
                got = rec.get(v["field"])
                ok = got not in (None, "") if v.get("filled") else str(got) == str(v["equals"])
                report["verify"].append({**v, "found": rec.get(v["field"]), "status": "pass" if ok else "fail"})
            failed = next((v for v in report["verify"] if v["status"] == "fail"), None)
        report["result"] = "PASS" if not failed else "FAIL"
        if failed:
            raw.unlink(missing_ok=True)
        else:
            make_video(raw, report["steps"], clips, out, voice, trim)
    finally:
        for rec in created.values():
            api.delete(rec)
        shutil.rmtree(out / "raw", ignore_errors=True)
        report["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (out / "qa-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "qa-report.md").write_text(qa_markdown(report), encoding="utf-8")
    return report


def make_video(raw: Path, steps: list[dict], clips, out: Path, voice: str, trim: float = 0.0) -> None:
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    srt = out / "subtitles.srt"
    srt.write_text("\n".join(f"{n}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['say']}\n" for n, s in enumerate(steps, 1)), encoding="utf-8")
    cmd = [ff, "-y", "-loglevel", "error"] + (["-ss", f"{trim:.2f}"] if trim > 0 else []) + ["-i", str(raw)]   # trim: the opening procedure, done off camera
    filters, mix = [], []
    if voice != "none":
        for n, (s, (_, wav)) in enumerate(zip(steps, clips), 1):
            cmd += ["-i", str(wav)]
            ms = int(s["start"] * 1000)
            filters.append(f"[{n}:a]adelay={ms}|{ms}[a{n}]")
            mix.append(f"[a{n}]")
    cmd += ["-i", str(srt)]
    sub_idx = len(mix) + 1
    filters.append("[0:v]scale=1920:1080:flags=lanczos,format=yuv420p[v]")
    if mix:
        filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0[a]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if mix:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-map", f"{sub_idx}:s", "-c:s", "mov_text", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-movflags", "+faststart", str(out / "video.mp4")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"ffmpeg failed: {r.stderr.strip()[-800:]}")


def qa_markdown(r: dict) -> str:
    lines = [f"# QA report: {r['procedure']} v{r['version']} ({r['lang'].upper()})", "",
             f"**Result: {r['result']}** · system {r['system']} ({r['app_version']}) · voice {r['voice']} · rules {r['rules_version']} · {r['started']}", "",
             "| Step | Status | Start (s) | Narration | Error |", "|---|---|---|---|---|"]
    for s in r["steps"]:
        lines.append(f"| {s['id']} | {s['status']} | {s['start']} | {s['say']} | {s.get('error', '')} |")
    if r["verify"]:
        lines += ["", "| Verify | Expected | Found | Status |", "|---|---|---|---|"]
        lines += [f"| {v['fixture']}.{v['field']} | {v.get('equals', 'any value')} | {v['found']} | {v['status']} |" for v in r["verify"]]
    return "\n".join(lines) + "\n"


def login(system: str, minutes: int) -> int:
    """Open the system in a visible browser, wait for the person to sign in, and keep the session.

    Nobody types the password but the person signing in: the session (cookies) is saved to
    .auth/<system>.json, which is git-ignored, and every later run reuses it until it expires.
    """
    from playwright.sync_api import sync_playwright

    api = system_named(system)
    dest = session_file(system)
    dest.parent.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, channel=BROWSER_CHANNEL)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()
        page.goto(api.url("/", "es"))
        print(f"Sign in to {system} in the browser window. Waiting up to {minutes} min...", flush=True)
        deadline = time.monotonic() + minutes * 60
        settled = 0.0
        while time.monotonic() < deadline:
            time.sleep(1)
            try:
                # back on the application's host (sign-in pages usually live on an identity provider's host)
                at_home = urlparse(page.url).netloc == urlparse(api.url("/", "es")).netloc
                asking = page.locator("input[type=password]:visible").count() > 0
            except Exception:  # noqa: BLE001 - page navigating
                continue
            settled = settled + 1 if at_home and not asking else 0
            if settled >= 5:   # five quiet seconds on the application, no password field
                ctx.storage_state(path=str(dest))
                print(f"Signed in. Session saved to {dest.relative_to(REPO).as_posix()} (git-ignored).")
                browser.close()
                return 0
        browser.close()
    print("Timed out before sign-in finished; nothing saved.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, nargs="?")
    ap.add_argument("--login", metavar="SYSTEM", help="sign in to a system once and keep the session")
    ap.add_argument("--login-minutes", type=int, default=5)
    ap.add_argument("--lang", nargs="+", choices=pc.LANGS, help="default: the system's languages (rules: systems.<name>.languages)")
    ap.add_argument("--voice", choices=["sapi", "piper", "none"], default="sapi" if os.name == "nt" else "piper")
    ap.add_argument("--out", type=Path, default=REPO / "build" / "procedures")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--start-demo", action="store_true", help="start the Paydesk demo app if it isn't running")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.login:
        return login(a.login, a.login_minutes)
    if not a.spec:
        ap.error("give a procedure.yaml, or --login SYSTEM")
    spec = load_yaml(a.spec)
    errors = [f for f in pc.lint(spec) if f.severity == "error"]
    if errors:
        for f in errors:
            print(f"{f.rule} {f.node or '-'}: {f.message}")
        print("Fix the procedure first: python tooling/procedure_check.py")
        return 2
    api = system_for(spec)
    a.lang = a.lang or pc.languages_for(spec)
    global STEP_TIMEOUT_S
    STEP_TIMEOUT_S = pc.rules()["systems"][spec["procedure"]["system"]].get("step_timeout_s", STEP_TIMEOUT_S)
    server = ensure_demo(api) if a.start_demo and isinstance(api, DemoApi) else None
    failed = 0
    try:
        for lang in a.lang:
            out = a.out / spec["procedure"]["id"] / lang
            r = run_lang(spec, api, lang, a.voice, out, a.headed)
            bad = next((s for s in r["steps"] if s["status"] == "fail"), None) or next((v for v in r["verify"] if v["status"] == "fail"), None)
            print(f"{r['result']}  {r['procedure']} {lang.upper()}  {len(r['steps'])}/{len(spec['steps'])} steps"
                  + (f"  -> {out / 'video.mp4'}" if r["result"] == "PASS" else f"  FAILED at {bad.get('id') or bad.get('field')}: {bad.get('error') or bad}"))
            failed += r["result"] != "PASS"
    finally:
        if server:
            server.terminate()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
