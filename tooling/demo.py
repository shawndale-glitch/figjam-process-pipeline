"""The two-act demo in one command: every guide passes, then a vendor release breaks one.

Act 1 starts Paydesk (the fictional demo app) and runs every procedure against it in English.
Act 2 restarts Paydesk with --drift, which renames the Approve button as a vendor release
might, and runs the approval procedure again: it must fail at the step that uses that button.
That failure is the point: the guide stopped matching the system and CI caught it first.

    python tooling/demo.py                 # both acts, headless (Codespaces, CI, any machine)
    python tooling/demo.py --headed        # watch the browser drive the app (your own laptop)
    python tooling/demo.py --serve         # afterwards, keep Paydesk running to try it by hand
    python tooling/demo.py --serve --drift # ...the drifted version, to see what changed

Needs the media extras: pip install -r requirements-media.txt && python -m playwright install chromium
Results are in build/demo/<procedure>/en/ (qa-report.md, step screenshots, the video when it passed).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "examples" / "procedure-demo" / "app" / "server.py"
RUNNER = REPO / "tooling" / "procedure_run.py"
OUT = REPO / "build" / "demo"
PORT = 8765                     # the demo-app system's base URL in governance/workflow-rules.yaml
DRIFT_TARGET = "P2P-03-P04"     # approve an invoice: uses the button --drift renames


def start_paydesk(drift: bool) -> subprocess.Popen:
    args = [sys.executable, str(SERVER), "--port", str(PORT)] + (["--drift"] if drift else [])
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        time.sleep(0.1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/version", timeout=1)
            return proc
        except OSError:
            if proc.poll() is not None:
                break
    proc.kill()
    raise SystemExit(f"Paydesk did not start on port {PORT}. Is something else using it?")


def run(spec: Path, headed: bool) -> bool:
    cmd = [sys.executable, str(RUNNER), str(spec), "--lang", "en", "--voice", "none", "--out", str(OUT)]
    return subprocess.run(cmd + (["--headed"] if headed else []), cwd=REPO).returncode == 0


def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}", flush=True)


def serve(drift: bool) -> None:
    proc = start_paydesk(drift)
    banner(f"Paydesk{' (drifted: Approve is now Authorise)' if drift else ''} is running: "
           f"http://127.0.0.1:{PORT}/?lang=en\n"
           "Follow any guide in docs/procedures/ by hand. Ctrl+C to stop.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--headed", action="store_true", help="show the browser while it runs")
    ap.add_argument("--serve", action="store_true", help="after the demo, keep Paydesk running to try by hand")
    ap.add_argument("--drift", action="store_true", help="with --serve: run the drifted Paydesk")
    ap.add_argument("--skip-acts", action="store_true", help="with --serve: only start Paydesk")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if a.serve and a.skip_acts:
        serve(a.drift)
        return 0

    specs = sorted(REPO.glob("procedures/*/*/procedure.yaml"))
    results: dict[str, bool] = {}

    banner(f"Act 1: every guide, run against Paydesk as it is today ({len(specs)} procedures)")
    proc = start_paydesk(drift=False)
    try:
        for spec in specs:
            results[spec.parent.name] = run(spec, a.headed)
    finally:
        proc.terminate()
        proc.wait()

    banner("Act 2: a vendor release renames Approve to Authorise. Same guide, run again.")
    drift_spec = next(s for s in specs if s.parent.name == DRIFT_TARGET)
    proc = start_paydesk(drift=True)
    try:
        drift_passed = run(drift_spec, a.headed)
    finally:
        proc.terminate()
        proc.wait()

    banner("Result")
    for pid, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {pid}  (today's Paydesk)")
    print(f"  {'PASS' if drift_passed else 'FAIL'}  {DRIFT_TARGET}  (after the release)"
          + ("" if drift_passed else "  <- expected: the guide no longer matches the screen"))
    report = OUT / DRIFT_TARGET / "en" / "qa-report.md"
    act1_ok = all(results.values())
    if act1_ok and not drift_passed:
        print(f"\nThe guide was caught out of date before any user followed it. Details: {report.relative_to(REPO).as_posix()}")
    elif drift_passed:
        print("\nUnexpected: the approval guide passed against the drifted app, so the gate missed the change.")
    else:
        print("\nUnexpected: a guide failed against today's Paydesk. See its qa-report.md under build/demo/.")

    if a.serve:
        serve(a.drift)
    return 0 if act1_ok and not drift_passed else 1


if __name__ == "__main__":
    sys.exit(main())
