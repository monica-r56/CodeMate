import os, httpx
from typing import Union
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
BASE = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}


def _get(path: str, params: dict = None) -> Union[dict, list]:
    r = httpx.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def get_open_prs(owner: str, repo: str, keyword: str = None) -> str:
    prs = _get(f"/repos/{owner}/{repo}/pulls", {"state": "open", "per_page": 20})
    if keyword:
        kw = keyword.lower()
        prs = [p for p in prs if kw in p["title"].lower() or kw in (p.get("body") or "").lower()]

    if not prs:
        return "No open pull requests found."

    lines = [f"Found {len(prs)} open PR(s):"]
    for p in prs[:5]:
        reviewer_logins = [r["login"] for r in p.get("requested_reviewers", [])]
        reviewers = ", ".join(reviewer_logins) if reviewer_logins else "none assigned"
        lines.append(
            f"• PR #{p['number']} — {p['title']} "
            f"(by {p['user']['login']}, reviewers: {reviewers})"
        )
    return "\n".join(lines)


def get_pr_details(owner: str, repo: str, pr_number: int) -> str:
    pr     = _get(f"/repos/{owner}/{repo}/pulls/{pr_number}")
    files  = _get(f"/repos/{owner}/{repo}/pulls/{pr_number}/files")
    reviews = _get(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")

    changed_files = [f["filename"] for f in files[:10]]
    review_lines  = []
    for r in reviews:
        if r["state"] in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED"):
            review_lines.append(f"{r['user']['login']}: {r['state']}")

    checks = _get(f"/repos/{owner}/{repo}/commits/{pr['head']['sha']}/check-runs")
    check_summary = "no checks"
    if isinstance(checks, dict) and checks.get("check_runs"):
        statuses = [c["conclusion"] or c["status"] for c in checks["check_runs"]]
        check_summary = ", ".join(set(statuses))

    return (
        f"PR #{pr_number}: {pr['title']}\n"
        f"Author: {pr['user']['login']} | State: {pr['state']} | Mergeable: {pr.get('mergeable')}\n"
        f"Changed files ({len(files)}): {', '.join(changed_files)}\n"
        f"Reviews: {', '.join(review_lines) or 'none yet'}\n"
        f"Checks: {check_summary}\n"
        f"Description: {(pr.get('body') or 'none')[:300]}"
    )


def get_build_status(owner: str, repo: str, branch: str = "main") -> str:
    runs = _get(f"/repos/{owner}/{repo}/actions/runs", {"branch": branch, "per_page": 5})
    if not isinstance(runs, dict) or not runs.get("workflow_runs"):
        return "No workflow runs found."

    latest = runs["workflow_runs"][0]
    conclusion = latest.get("conclusion") or latest.get("status", "unknown")
    return (
        f"Latest build on '{branch}': {conclusion.upper()}\n"
        f"Workflow: {latest['name']}\n"
        f"Triggered by: {latest['event']} at {latest['created_at']}\n"
        f"URL: {latest['html_url']}"
    )


def get_recent_commits(owner: str, repo: str, branch: str = "main", count: int = 5) -> str:
    commits = _get(f"/repos/{owner}/{repo}/commits", {"sha": branch, "per_page": count})
    if not commits:
        return "No commits found."

    lines = [f"Last {len(commits)} commits on '{branch}':"]
    for c in commits:
        sha   = c["sha"][:7]
        msg   = c["commit"]["message"].splitlines()[0][:80]
        author = c["commit"]["author"]["name"]
        lines.append(f"• {sha} — {msg} ({author})")
    return "\n".join(lines)


def create_pull_request(owner: str, repo: str, title: str, body: str,
                        head: str, base: str = "main", assignee: str = None) -> str:
    payload = {"title": title, "body": body, "head": head, "base": base}
    r = httpx.post(
        f"{BASE}/repos/{owner}/{repo}/pulls",
        headers=HEADERS,
        json=payload,
        timeout=10
    )
    r.raise_for_status()
    pr = r.json()

    if assignee:
        httpx.post(
            f"{BASE}/repos/{owner}/{repo}/issues/{pr['number']}/assignees",
            headers=HEADERS,
            json={"assignees": [assignee]},
            timeout=10
        )

    return f"PR #{pr['number']} created: {pr['html_url']}"
