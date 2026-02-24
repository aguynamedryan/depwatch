"""Tests for depwatch CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from depwatch.cli import cli


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    config = tmp_path / "depwatch.toml"
    config.write_text(
        'slack_webhook_url = "https://hooks.slack.com/services/XXX/YYY/ZZZ"\n'
        "\n"
        "repos = [\n"
        '  "owner/repo1",\n'
        "]\n"
    )
    return config


def _mock_gh_with_prs(cmd, **kwargs):
    return type(
        "Result",
        (),
        {
            "returncode": 0,
            "stdout": json.dumps(
                [
                    {
                        "title": "Bump requests from 2.31.0 to 2.32.0",
                        "url": "https://github.com/owner/repo1/pull/42",
                        "createdAt": "2026-02-20T12:00:00Z",
                    }
                ]
            ),
            "stderr": "",
        },
    )()


def _mock_gh_no_prs(cmd, **kwargs):
    return type("Result", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()


class TestCheckCommand:
    def test_dry_run_shows_output(self, config_file: Path) -> None:
        runner = CliRunner()
        with patch("depwatch.main.subprocess.run", side_effect=_mock_gh_with_prs):
            result = runner.invoke(cli, ["check", "--config", str(config_file), "--dry-run"])

        assert result.exit_code == 0
        assert "[dry-run]" in result.output
        assert "Bump requests" in result.output

    def test_no_prs_exits_cleanly(self, config_file: Path) -> None:
        runner = CliRunner()
        with patch("depwatch.main.subprocess.run", side_effect=_mock_gh_no_prs):
            result = runner.invoke(cli, ["check", "--config", str(config_file)])

        assert result.exit_code == 0
        assert "All clear" in result.output

    def test_posts_to_slack_when_prs_found(self, config_file: Path) -> None:
        runner = CliRunner()
        with (
            patch("depwatch.main.subprocess.run", side_effect=_mock_gh_with_prs),
            patch("depwatch.cli.post_to_slack") as mock_post,
        ):
            result = runner.invoke(cli, ["check", "--config", str(config_file)])

        assert result.exit_code == 0
        mock_post.assert_called_once()
        webhook_url = mock_post.call_args[0][0]
        assert webhook_url == "https://hooks.slack.com/services/XXX/YYY/ZZZ"

    def test_missing_config_shows_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--config", "/nonexistent/config.toml"])
        assert result.exit_code != 0

    def test_version_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
