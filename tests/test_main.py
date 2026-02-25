"""Tests for depwatch core logic."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from depwatch.main import (
    DependabotPR,
    SecurityAlert,
    check_all_repos,
    check_all_repos_security,
    fetch_dependabot_prs,
    fetch_security_alerts,
    format_slack_message,
    format_slack_security_message,
    load_config,
)


@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    config_file = tmp_path / "depwatch.toml"
    config_file.write_text(
        'slack_webhook_url = "https://hooks.slack.com/services/XXX/YYY/ZZZ"\n'
        "\n"
        "repos = [\n"
        '  "owner/repo1",\n'
        '  "owner/repo2",\n'
        "]\n"
    )
    return config_file


@pytest.fixture
def bad_config_no_repos(tmp_path: Path) -> Path:
    config_file = tmp_path / "depwatch.toml"
    config_file.write_text('slack_webhook_url = "https://hooks.slack.com/services/XXX/YYY/ZZZ"\n')
    return config_file


@pytest.fixture
def bad_config_no_webhook(tmp_path: Path) -> Path:
    config_file = tmp_path / "depwatch.toml"
    config_file.write_text('repos = ["owner/repo1"]\n')
    return config_file


@pytest.fixture
def sample_prs() -> list[DependabotPR]:
    return [
        DependabotPR(
            repo="owner/repo1",
            title="Bump requests from 2.31.0 to 2.32.0",
            url="https://github.com/owner/repo1/pull/42",
            created_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
        ),
        DependabotPR(
            repo="owner/repo2",
            title="Bump lodash from 4.17.20 to 4.17.21",
            url="https://github.com/owner/repo2/pull/7",
            created_at=datetime(2026, 2, 10, 8, 0, 0, tzinfo=UTC),
        ),
    ]


class TestLoadConfig:
    def test_loads_valid_config(self, sample_config: Path) -> None:
        config = load_config(sample_config)
        assert config["slack_webhook_url"] == "https://hooks.slack.com/services/XXX/YYY/ZZZ"
        assert config["repos"] == ["owner/repo1", "owner/repo2"]

    def test_missing_repos_key(self, bad_config_no_repos: Path) -> None:
        with pytest.raises(AssertionError, match="missing 'repos'"):
            load_config(bad_config_no_repos)

    def test_missing_webhook_key(self, bad_config_no_webhook: Path) -> None:
        with pytest.raises(AssertionError, match="missing 'slack_webhook_url'"):
            load_config(bad_config_no_webhook)

    def test_empty_repos(self, tmp_path: Path) -> None:
        config_file = tmp_path / "depwatch.toml"
        config_file.write_text(
            'slack_webhook_url = "https://hooks.slack.com/services/XXX"\nrepos = []\n'
        )
        with pytest.raises(AssertionError, match="empty"):
            load_config(config_file)


class TestFetchDependabotPrs:
    def test_returns_prs_from_gh_output(self) -> None:
        gh_output = json.dumps(
            [
                {
                    "title": "Bump requests from 2.31.0 to 2.32.0",
                    "url": "https://github.com/owner/repo1/pull/42",
                    "createdAt": "2026-02-20T12:00:00Z",
                }
            ]
        )
        mock_result = type("Result", (), {"returncode": 0, "stdout": gh_output, "stderr": ""})()

        with patch("depwatch.main.subprocess.run", return_value=mock_result):
            prs = fetch_dependabot_prs("owner/repo1")

        assert len(prs) == 1
        assert prs[0].repo == "owner/repo1"
        assert prs[0].title == "Bump requests from 2.31.0 to 2.32.0"
        assert prs[0].url == "https://github.com/owner/repo1/pull/42"

    def test_returns_empty_list_when_no_prs(self) -> None:
        mock_result = type("Result", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()

        with patch("depwatch.main.subprocess.run", return_value=mock_result):
            prs = fetch_dependabot_prs("owner/repo1")

        assert prs == []

    def test_raises_on_gh_failure(self) -> None:
        mock_result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "not found"})()

        with (
            patch("depwatch.main.subprocess.run", return_value=mock_result),
            pytest.raises(RuntimeError, match="gh pr list failed"),
        ):
            fetch_dependabot_prs("owner/repo1")


class TestCheckAllRepos:
    def test_aggregates_prs_from_multiple_repos(self) -> None:
        gh_outputs = {
            "owner/repo1": json.dumps(
                [
                    {
                        "title": "Bump A",
                        "url": "https://github.com/owner/repo1/pull/1",
                        "createdAt": "2026-02-20T12:00:00Z",
                    }
                ]
            ),
            "owner/repo2": json.dumps(
                [
                    {
                        "title": "Bump B",
                        "url": "https://github.com/owner/repo2/pull/2",
                        "createdAt": "2026-02-19T12:00:00Z",
                    }
                ]
            ),
        }

        def mock_run(cmd, **kwargs):
            repo = cmd[cmd.index("--repo") + 1]
            return type("Result", (), {"returncode": 0, "stdout": gh_outputs[repo], "stderr": ""})()

        with patch("depwatch.main.subprocess.run", side_effect=mock_run):
            prs = check_all_repos(["owner/repo1", "owner/repo2"])

        assert len(prs) == 2
        assert {pr.repo for pr in prs} == {"owner/repo1", "owner/repo2"}


class TestFormatSlackMessage:
    def test_formats_message_with_prs(self, sample_prs: list[DependabotPR]) -> None:
        payload = format_slack_message(sample_prs)
        text = payload["text"]
        assert "2 stuck Dependabot PR(s)" in text
        assert "owner/repo1" in text
        assert "owner/repo2" in text
        assert "Bump requests" in text
        assert "Bump lodash" in text

    def test_includes_pr_urls(self, sample_prs: list[DependabotPR]) -> None:
        payload = format_slack_message(sample_prs)
        text = payload["text"]
        assert "https://github.com/owner/repo1/pull/42" in text
        assert "https://github.com/owner/repo2/pull/7" in text

    def test_older_prs_listed_first(self, sample_prs: list[DependabotPR]) -> None:
        payload = format_slack_message(sample_prs)
        text = payload["text"]
        # repo2 PR (Feb 10) should appear before repo1 PR (Feb 20)
        repo2_pos = text.index("owner/repo2")
        repo1_pos = text.index("owner/repo1")
        assert repo2_pos < repo1_pos


class TestDependabotPR:
    def test_age_days(self) -> None:
        pr = DependabotPR(
            repo="owner/repo",
            title="Bump something",
            url="https://github.com/owner/repo/pull/1",
            created_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
        )
        # age_days depends on current time, just verify it's non-negative
        assert pr.age_days >= 0


# --- Security alert tests ---


@pytest.fixture
def sample_alerts() -> list[SecurityAlert]:
    return [
        SecurityAlert(
            repo="owner/repo1",
            severity="critical",
            package="requests",
            ecosystem="pip",
            vulnerable_range="< 2.32.0",
            patched_version="2.32.0",
            advisory_url="https://github.com/owner/repo1/security/dependabot/1",
            summary="SSRF vulnerability in requests",
        ),
        SecurityAlert(
            repo="owner/repo2",
            severity="high",
            package="lodash",
            ecosystem="npm",
            vulnerable_range="< 4.17.21",
            patched_version="4.17.21",
            advisory_url="https://github.com/owner/repo2/security/dependabot/5",
            summary="Prototype pollution in lodash",
        ),
        SecurityAlert(
            repo="owner/repo1",
            severity="low",
            package="urllib3",
            ecosystem="pip",
            vulnerable_range="< 2.0.7",
            patched_version=None,
            advisory_url="https://github.com/owner/repo1/security/dependabot/3",
            summary="Minor info leak in urllib3",
        ),
    ]


def _gh_api_alerts_json() -> str:
    return json.dumps(
        [
            {
                "severity": "critical",
                "package": "requests",
                "ecosystem": "pip",
                "vulnerable_range": "< 2.32.0",
                "patched_version": "2.32.0",
                "advisory_url": "https://github.com/owner/repo1/security/dependabot/1",
                "summary": "SSRF vulnerability in requests",
            }
        ]
    )


class TestFetchSecurityAlerts:
    def test_returns_alerts_from_gh_output(self) -> None:
        mock_result = type(
            "Result", (), {"returncode": 0, "stdout": _gh_api_alerts_json(), "stderr": ""}
        )()

        with patch("depwatch.main.subprocess.run", return_value=mock_result):
            alerts = fetch_security_alerts("owner/repo1")

        assert len(alerts) == 1
        assert alerts[0].repo == "owner/repo1"
        assert alerts[0].severity == "critical"
        assert alerts[0].package == "requests"
        assert alerts[0].patched_version == "2.32.0"

    def test_returns_empty_list_when_no_alerts(self) -> None:
        mock_result = type("Result", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()

        with patch("depwatch.main.subprocess.run", return_value=mock_result):
            alerts = fetch_security_alerts("owner/repo1")

        assert alerts == []

    def test_raises_on_gh_failure(self) -> None:
        mock_result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "forbidden"})()

        with (
            patch("depwatch.main.subprocess.run", return_value=mock_result),
            pytest.raises(RuntimeError, match="gh api dependabot/alerts failed"),
        ):
            fetch_security_alerts("owner/repo1")

    def test_handles_null_patched_version(self) -> None:
        gh_output = json.dumps(
            [
                {
                    "severity": "low",
                    "package": "urllib3",
                    "ecosystem": "pip",
                    "vulnerable_range": "< 2.0.7",
                    "patched_version": None,
                    "advisory_url": "https://github.com/owner/repo1/security/dependabot/3",
                    "summary": "Minor info leak",
                }
            ]
        )
        mock_result = type("Result", (), {"returncode": 0, "stdout": gh_output, "stderr": ""})()

        with patch("depwatch.main.subprocess.run", return_value=mock_result):
            alerts = fetch_security_alerts("owner/repo1")

        assert alerts[0].patched_version is None


class TestCheckAllReposSecurity:
    def test_aggregates_alerts_from_multiple_repos(self) -> None:
        gh_outputs = {
            "owner/repo1": json.dumps(
                [
                    {
                        "severity": "critical",
                        "package": "requests",
                        "ecosystem": "pip",
                        "vulnerable_range": "< 2.32.0",
                        "patched_version": "2.32.0",
                        "advisory_url": "https://github.com/owner/repo1/security/dependabot/1",
                        "summary": "SSRF vulnerability",
                    }
                ]
            ),
            "owner/repo2": json.dumps(
                [
                    {
                        "severity": "high",
                        "package": "lodash",
                        "ecosystem": "npm",
                        "vulnerable_range": "< 4.17.21",
                        "patched_version": "4.17.21",
                        "advisory_url": "https://github.com/owner/repo2/security/dependabot/5",
                        "summary": "Prototype pollution",
                    }
                ]
            ),
        }

        def mock_run(cmd, **kwargs):
            # Extract repo from the gh api URL pattern: /repos/{repo}/dependabot/alerts
            for arg in cmd:
                if arg.startswith("/repos/"):
                    repo = "/".join(arg.split("/")[2:4])
                    break
            return type("Result", (), {"returncode": 0, "stdout": gh_outputs[repo], "stderr": ""})()

        with patch("depwatch.main.subprocess.run", side_effect=mock_run):
            alerts = check_all_repos_security(["owner/repo1", "owner/repo2"])

        assert len(alerts) == 2
        assert {a.repo for a in alerts} == {"owner/repo1", "owner/repo2"}


class TestFormatSlackSecurityMessage:
    def test_formats_message_with_alerts(self, sample_alerts: list[SecurityAlert]) -> None:
        payload = format_slack_security_message(sample_alerts)
        text = payload["text"]
        assert "3 open Dependabot security alert(s)" in text
        assert "owner/repo1" in text
        assert "owner/repo2" in text
        assert "CRITICAL" in text
        assert "HIGH" in text
        assert "LOW" in text

    def test_critical_alerts_listed_first(self, sample_alerts: list[SecurityAlert]) -> None:
        payload = format_slack_security_message(sample_alerts)
        text = payload["text"]
        critical_pos = text.index("CRITICAL")
        high_pos = text.index("HIGH")
        low_pos = text.index("LOW")
        assert critical_pos < high_pos < low_pos

    def test_shows_patched_version(self, sample_alerts: list[SecurityAlert]) -> None:
        payload = format_slack_security_message(sample_alerts)
        text = payload["text"]
        assert "fix: 2.32.0" in text

    def test_shows_no_fix_when_unpatched(self, sample_alerts: list[SecurityAlert]) -> None:
        payload = format_slack_security_message(sample_alerts)
        text = payload["text"]
        assert "no fix available" in text

    def test_includes_advisory_urls(self, sample_alerts: list[SecurityAlert]) -> None:
        payload = format_slack_security_message(sample_alerts)
        text = payload["text"]
        assert "security/dependabot/1" in text
        assert "security/dependabot/5" in text

    def test_includes_summaries(self, sample_alerts: list[SecurityAlert]) -> None:
        payload = format_slack_security_message(sample_alerts)
        text = payload["text"]
        assert "SSRF vulnerability" in text
        assert "Prototype pollution" in text
