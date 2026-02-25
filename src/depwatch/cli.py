"""CLI entry point for depwatch."""

from __future__ import annotations

from pathlib import Path

import click

from depwatch.main import (
    DEFAULT_CONFIG_PATH,
    check_all_repos,
    check_all_repos_security,
    format_slack_message,
    format_slack_security_message,
    load_config,
    post_to_slack,
)


@click.group()
@click.version_option()
def cli() -> None:
    """Monitor GitHub repos for stuck Dependabot PRs."""


@cli.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_CONFIG_PATH,
    help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be sent to Slack instead of posting",
)
def check(config_path: Path, dry_run: bool) -> None:
    """Check all configured repos for open Dependabot PRs."""
    config = load_config(config_path)
    prs = check_all_repos(config["repos"])

    if not prs:
        print("No open Dependabot PRs found. All clear!")
        return

    payload = format_slack_message(prs)

    if dry_run:
        print("\n[dry-run] Would send to Slack:\n")
        print(payload["text"])
        return

    post_to_slack(config["slack_webhook_url"], payload)
    print(f"Posted {len(prs)} PR(s) to Slack.")


@cli.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_CONFIG_PATH,
    help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be sent to Slack instead of posting",
)
def security(config_path: Path, dry_run: bool) -> None:
    """Check all configured repos for open Dependabot security alerts."""
    config = load_config(config_path)
    alerts = check_all_repos_security(config["repos"])

    if not alerts:
        print("No open security alerts found. All clear!")
        return

    payload = format_slack_security_message(alerts)

    if dry_run:
        print("\n[dry-run] Would send to Slack:\n")
        print(payload["text"])
        return

    post_to_slack(config["slack_webhook_url"], payload)
    print(f"Posted {len(alerts)} security alert(s) to Slack.")
