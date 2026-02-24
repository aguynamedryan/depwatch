# depwatch

Monitor GitHub repos for stuck Dependabot PRs and get notified via Slack.

Repos with Dependabot + auto-merge enabled should have their PRs merge automatically. When one doesn't (CI failure, merge conflict, etc.), it slips through silently. depwatch checks all your configured repos for open Dependabot PRs and posts a Slack notification if any are found.

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install depwatch
```

Or clone and install locally:

```bash
git clone https://github.com/aguynamedryan/depwatch.git
cd depwatch
uv sync
```

## Setup

### 1. Create a Slack Incoming Webhook

Go to [Slack API: Incoming Webhooks](https://api.slack.com/messaging/webhooks) and create a webhook for the channel where you want notifications.

### 2. Create a config file

```bash
mkdir -p ~/.config/depwatch
cp depwatch.toml.example ~/.config/depwatch/depwatch.toml
```

Edit `~/.config/depwatch/depwatch.toml`:

```toml
slack_webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

repos = [
  "your-org/repo1",
  "your-org/repo2",
]
```

### 3. Ensure `gh` CLI is authenticated

depwatch uses the [GitHub CLI](https://cli.github.com/) (`gh`) to query PRs. Make sure it's installed and authenticated:

```bash
gh auth status
```

## Usage

Check for stuck Dependabot PRs:

```bash
depwatch check
```

Preview what would be sent to Slack without actually posting:

```bash
depwatch check --dry-run
```

Use a custom config file:

```bash
depwatch check --config /path/to/depwatch.toml
```

### Cron Setup

Run weekly on Monday at 9am:

```bash
crontab -e
```

Add:

```
0 9 * * 1 $HOME/.local/bin/uv tool run depwatch check >> ~/.local/share/depwatch/depwatch.log 2>&1
```

## How It Works

1. Reads your config file listing GitHub repos to monitor
2. For each repo, runs `gh pr list --author "app/dependabot" --state open`
3. If any open Dependabot PRs are found, posts a formatted message to Slack
4. If none are found, exits silently (no noise when things are healthy)

## Development

```bash
git clone https://github.com/aguynamedryan/depwatch.git
cd depwatch
uv sync
```

Run tests:

```bash
uv run pytest -v
```

Lint and format:

```bash
uv run ruff check .
uv run ruff format .
```

## License

MIT
