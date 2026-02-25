"""Core logic for checking Dependabot PRs and sending Slack notifications."""

from __future__ import annotations

import json
import subprocess
import tomllib
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/depwatch/depwatch.toml").expanduser()


@dataclass
class DependabotPR:
    repo: str
    title: str
    url: str
    created_at: datetime

    @property
    def age_days(self) -> int:
        delta = datetime.now(UTC) - self.created_at
        return delta.days


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class SecurityAlert:
    repo: str
    severity: str
    package: str
    ecosystem: str
    vulnerable_range: str
    patched_version: str | None
    advisory_url: str
    summary: str


def load_config(config_path: Path) -> dict:
    """Load and return the TOML config file."""
    print(f"[debug] Loading config from {config_path}")
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    assert "repos" in config, f"Config missing 'repos' key: {config_path}"
    assert "slack_webhook_url" in config, f"Config missing 'slack_webhook_url' key: {config_path}"
    assert len(config["repos"]) > 0, "Config 'repos' list is empty"

    print(f"[debug] Found {len(config['repos'])} repos to check")
    return config


def fetch_dependabot_prs(repo: str) -> list[DependabotPR]:
    """Fetch open Dependabot PRs for a single repo using `gh`."""
    print(f"[debug] Checking {repo}...")
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--author",
        "app/dependabot",
        "--state",
        "open",
        "--json",
        "url,title,createdAt",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh pr list failed for {repo}: {result.stderr.strip()}")

    prs_data = json.loads(result.stdout)
    prs = []
    for pr in prs_data:
        created = datetime.fromisoformat(pr["createdAt"])
        prs.append(
            DependabotPR(
                repo=repo,
                title=pr["title"],
                url=pr["url"],
                created_at=created,
            )
        )

    print(f"[debug]   Found {len(prs)} open Dependabot PR(s)")
    return prs


def fetch_security_alerts(repo: str) -> list[SecurityAlert]:
    """Fetch open Dependabot security alerts for a single repo using `gh api`."""
    print(f"[debug] Checking security alerts for {repo}...")
    cmd = [
        "gh",
        "api",
        f"/repos/{repo}/dependabot/alerts",
        "--jq",
        '[.[] | select(.state == "open") | {'
        "number, severity: .security_advisory.severity,"
        "package: .dependency.package.name,"
        "ecosystem: .dependency.package.ecosystem,"
        "vulnerable_range: .security_vulnerability.vulnerable_version_range,"
        "patched_version: (.security_vulnerability.first_patched_version.identifier // null),"
        "advisory_url: .html_url,"
        "summary: .security_advisory.summary"
        "}]",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api dependabot/alerts failed for {repo}: {result.stderr.strip()}")

    alerts_data = json.loads(result.stdout)
    alerts = []
    for alert in alerts_data:
        alerts.append(
            SecurityAlert(
                repo=repo,
                severity=alert["severity"],
                package=alert["package"],
                ecosystem=alert["ecosystem"],
                vulnerable_range=alert["vulnerable_range"],
                patched_version=alert.get("patched_version"),
                advisory_url=alert["advisory_url"],
                summary=alert["summary"],
            )
        )

    print(f"[debug]   Found {len(alerts)} open security alert(s)")
    return alerts


def check_all_repos_security(repos: list[str]) -> list[SecurityAlert]:
    """Check all configured repos and return any open security alerts."""
    all_alerts = []
    for repo in repos:
        alerts = fetch_security_alerts(repo)
        all_alerts.extend(alerts)
    return all_alerts


def check_all_repos(repos: list[str]) -> list[DependabotPR]:
    """Check all configured repos and return any open Dependabot PRs."""
    all_prs = []
    for repo in repos:
        prs = fetch_dependabot_prs(repo)
        all_prs.extend(prs)
    return all_prs


def format_slack_message(prs: list[DependabotPR]) -> dict:
    """Format PRs into a Slack webhook payload."""
    lines = [f"*:warning: {len(prs)} stuck Dependabot PR(s) found:*\n"]

    for pr in sorted(prs, key=lambda p: p.created_at):
        age = pr.age_days
        age_str = f"{age} day{'s' if age != 1 else ''}"
        lines.append(f"• *{pr.repo}*: <{pr.url}|{pr.title}> ({age_str} old)")

    return {"text": "\n".join(lines)}


def format_slack_security_message(alerts: list[SecurityAlert]) -> dict:
    """Format security alerts into a Slack webhook payload."""
    lines = [f"*:rotating_light: {len(alerts)} open Dependabot security alert(s) found:*\n"]

    sorted_alerts = sorted(alerts, key=lambda a: SEVERITY_ORDER.get(a.severity, 99))

    for alert in sorted_alerts:
        severity_upper = alert.severity.upper()
        if alert.patched_version:
            patched = f" (fix: {alert.patched_version})"
        else:
            patched = " (no fix available)"
        link = (
            f"<{alert.advisory_url}"
            f"|{alert.package} {alert.vulnerable_range}>"
        )
        lines.append(
            f"• [{severity_upper}] *{alert.repo}*: "
            f"{link}{patched}\n"
            f"  _{alert.summary}_"
        )

    return {"text": "\n".join(lines)}


def post_to_slack(webhook_url: str, payload: dict) -> None:
    """POST a JSON payload to a Slack incoming webhook."""
    print("[debug] Posting to Slack webhook...")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        print(f"[debug] Slack response: {resp.status}")
