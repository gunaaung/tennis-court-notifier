"""LINE Messaging API push notification sender."""

from __future__ import annotations

import httpx

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line_push(
    channel_access_token: str,
    to_id: str,
    text: str,
    timeout: float = 15.0,
) -> None:
    """Send a push text message via LINE Messaging API."""
    if not channel_access_token or not to_id:
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID must be set")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}",
    }
    payload = {
        "to": to_id,
        "messages": [{"type": "text", "text": text}],
    }

    response = httpx.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(
            f"LINE Messaging API error ({response.status_code}): {response.text}"
        )
