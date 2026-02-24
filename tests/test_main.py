"""Tests for depwatch core logic."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from depwatch.main import (
    DependabotPR,
    check_all_repos,
    fetch_dependabot_prs,
    format_slack_message,
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
