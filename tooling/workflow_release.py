"""Release validated workflow versions after merge to main.

Called by .github/workflows/workflow-release.yml:
  python tooling/workflow_release.py --since <before-sha> [--dry-run]

For every workflows/**/workflow.yaml changed since <before-sha>:
  1. skip unless status is `validated` (drafts are never released)
  2. re-check the schema
  3. verify the merged PR was approved by someone other than its author (versioning.release_requires)
  4. skip if tag <ID>@<version> already exists
  5. tag, build the bundle, create the GitHub release
  6. notify consumers (workflows/consumers.yaml): major -> issue in the consumer repo

Needs: git, gh (GitHub CLI), GH_TOKEN. CONSUMER_NOTIFY_TOKEN (a PAT or app token with
issues:write on consumer repos) is used for cross-repo issues; without it they're skipped.
Rules: governance/workflow-rules.yaml (versioning.release_requires, versioning.on_release).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_core as core  # noqa: E402

REPO = core.REPO
ZERO = "0" * 40


def sh(*args: str, check: bool = True, env: dict | None = None) -> str:
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def semver(s: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in s.split("."))  # type: ignore[return-value]


def changed_workflows(since: str) -> list[Path]:
    known = bool(since) and since != ZERO and subprocess.run(
        ["git", "cat-file", "-e", f"{since}^{{commit}}"], cwd=REPO, capture_output=True).returncode == 0
    if known:
        files = sh("git", "diff", "--name-only", since, "HEAD", "--", "workflows/*/*/workflow.yaml").splitlines()
    else:  # first push of a branch, force-push, or shallow history: consider every workflow
        files = sh("git", "ls-files", "workflows/*/*/workflow.yaml").splitlines()
    return [REPO / f for f in files if (REPO / f).exists()]


def previous_release(pid: str, current: str) -> str | None:
    vs = [t.split("@", 1)[1] for t in sh("git", "tag", "-l", f"{pid}@*").splitlines()]
    older = sorted((v for v in vs if re.fullmatch(r"\d+\.\d+\.\d+", v) and semver(v) < semver(current)), key=semver)
    return older[-1] if older else None


def merged_pr_approved(repo: str) -> tuple[bool, str]:
    """Check the PR that produced HEAD has an APPROVED review by someone other than its author."""
    sha = sh("git", "rev-parse", "HEAD")
    prs = json.loads(sh("gh", "api", f"repos/{repo}/commits/{sha}/pulls") or "[]")
    if not prs:
        return False, f"commit {sha[:8]} did not come from a pull request"
    pr = prs[0]
    reviews = json.loads(sh("gh", "api", f"repos/{repo}/pulls/{pr['number']}/reviews") or "[]")
    approvers = sorted({r["user"]["login"] for r in reviews if r["state"] == "APPROVED" and r["user"]["login"] != pr["user"]["login"]})
    if not approvers:
        return False, f"PR #{pr['number']} has no approval from someone other than its author"
    return True, f"PR #{pr['number']} approved by {', '.join('@' + a for a in approvers)}"


def changelog_entry(path: Path, version: str) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(rf"^## {re.escape(version)}\b.*?(?=^## |\Z)", text, re.S | re.M)
    return m.group(0).strip() if m else f"## {version}"


def bundle(wf: dict, wdir: Path) -> Path:
    pid, ver = wf["process"]["id"], wf["process"]["version"]
    out = REPO / "dist" / f"{pid}-{ver}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files = [wdir / "workflow.yaml", wdir / "CHANGELOG.md", wdir / "board.json",
             REPO / "conformance" / pid / "scenarios.feature", REPO / "conformance" / pid / "bindings.yaml"]
    for f in files:
        if f.exists():
            shutil.copy2(f, out / f.name)
    z = out.parent / f"{out.name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out.iterdir()):
            zf.write(f, f"{pid}-{ver}/{f.name}")
    return z


def consumers_for(pid: str) -> list[dict]:
    path = REPO / "workflows" / "consumers.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return [c for c in (data or {}).get("consumers", []) if any(i.get("process") == pid for i in c.get("implements", []))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    summary = ["# Workflow release", ""]
    failed = False
    for path in changed_workflows(a.since):
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        p = wf["process"]
        pid, ver, tag = p["id"], p["version"], f"{p['id']}@{p['version']}"
        if p["status"] != "validated":
            summary.append(f"- `{pid}` {ver}: status `{p['status']}`, not released (only validated versions are)")
            continue
        errs = core.schema_errors(wf)
        if errs:
            failed = True
            summary.append(f"- ❌ `{pid}` {ver}: schema errors, not released: {errs[:3]}")
            continue
        if sh("git", "tag", "-l", tag):
            summary.append(f"- `{tag}` already released")
            continue
        if a.repo and not a.dry_run:
            ok, why = merged_pr_approved(a.repo)
            if not ok:
                failed = True
                summary.append(f"- ❌ `{tag}`: {why}; not released")
                continue
            summary.append(f"- `{tag}`: {why}")
        prev = previous_release(pid, ver)
        level = "initial" if prev is None else ("major" if semver(ver)[0] > semver(prev)[0] else "minor" if semver(ver)[1] > semver(prev)[1] else "patch")
        zipf = bundle(wf, path.parent)
        notes = changelog_entry(path.parent / "CHANGELOG.md", ver)
        notes_file = zipf.parent / f"{zipf.stem}.md"
        notes_file.write_text(f"{notes}\n\nPrevious release: {prev or 'none'} · Change level: **{level}**\n", encoding="utf-8")
        if a.dry_run:
            summary.append(f"- (dry run) would tag and release `{tag}` ({level}), bundle `{zipf.relative_to(REPO)}`")
        else:
            sh("git", "tag", "-a", tag, "-m", f"{pid} {ver}")
            sh("git", "push", "origin", tag)
            sh("gh", "release", "create", tag, str(zipf), "--title", f"{pid} {p['name']} {ver}", "--notes-file", str(notes_file))
            summary.append(f"- ✅ released `{tag}` ({level})")

        for c in consumers_for(pid):
            repo = c.get("repo", "")
            if "TBC" in repo or not repo:
                summary.append(f"  - consumer `{c.get('id')}`: repo is TBC, not notified")
                continue
            if level != "major":
                summary.append(f"  - consumer `{c['id']}`: {level} change, release notes only")
                continue
            token = os.environ.get("CONSUMER_NOTIFY_TOKEN")
            title = f"[{pid}] Major release {ver}: update implementation and re-run conformance"
            body = (f"{pid} ({p['name']}) moved from {prev} to **{ver}**, a major change.\n\n{notes}\n\n"
                    f"Your pin in workflows/consumers.yaml no longer covers it. Update bindings, re-run conformance, then move the pin.")
            if a.dry_run or not token:
                summary.append(f"  - consumer `{c['id']}`: would open issue in `{repo}`" + ("" if a.dry_run else " (CONSUMER_NOTIFY_TOKEN not set)"))
            else:
                sh("gh", "issue", "create", "-R", repo, "--title", title, "--body", body, env={"GH_TOKEN": token})
                summary.append(f"  - consumer `{c['id']}`: issue opened in `{repo}`")

    if len(summary) == 2:
        summary.append("No workflow files changed.")
    text = "\n".join(summary) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
