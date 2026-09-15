import json
import urllib.request

import boto3


def get_slack_webhook() -> str:
    """
    Retrieve the Slack Incoming Webhook URL from SSM Parameter Store.
    """

    ssm = boto3.client(
        "ssm",
        region_name="us-east-1",
    )

    response = ssm.get_parameter(
        Name="/sentinel/slack-webhook",
        WithDecryption=True,
    )

    return response["Parameter"]["Value"]


def send_slack_message(message: str) -> None:
    """
    Send a plain-text message to the configured Slack channel.
    """

    webhook_url = get_slack_webhook()

    payload = json.dumps(
        {
            "text": message,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=10,
    ) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(
                f"Slack webhook returned HTTP {response.status}"
            )