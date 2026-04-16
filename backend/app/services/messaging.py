from __future__ import annotations

from app.core.config import settings


def list_messaging_platforms() -> list[dict[str, object]]:
    slack_missing = []
    if not settings.slack_bot_token:
        slack_missing.append("SLACK_BOT_TOKEN")
    if not settings.slack_signing_secret:
        slack_missing.append("SLACK_SIGNING_SECRET")

    teams_missing = []
    if not settings.teams_app_id:
        teams_missing.append("TEAMS_APP_ID")
    if not settings.teams_app_password:
        teams_missing.append("TEAMS_APP_PASSWORD")

    return [
        {
            "name": "Slack Bolt",
            "enabled": not slack_missing,
            "missing_configuration": slack_missing,
            "notes": "Use this as the webhook/command integration entrypoint for Slack.",
        },
        {
            "name": "Microsoft Teams",
            "enabled": not teams_missing,
            "missing_configuration": teams_missing,
            "notes": "Use this as the bot framework wiring point for Microsoft Teams.",
        },
    ]

