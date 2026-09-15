import json
import sys
import time

from agent.agent import investigate
from agent.review_pipeline import review_and_revise
from agent.tools import fetch_alarm_history
from agent.notifier import send_slack_message

MAX_HISTORY_ATTEMPTS = 3
HISTORY_RETRY_DELAY_SECONDS = 2


def _get_selected_incident_with_retry() -> dict:
    """
    Retrieve the canonical incident deterministically.

    Retry only the AWS alarm-history lookup. The LLM is not involved
    in deciding whether another attempt is required.
    """

    last_result = None

    for attempt in range(1, MAX_HISTORY_ATTEMPTS + 1):
        try:
            result = fetch_alarm_history()

        except Exception as exc:
            last_result = {
                "status": "error",
                "message": (
                    f"Alarm history lookup failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "attempt": attempt,
            }

        else:
            last_result = result

            if (
                result.get("status") == "success"
                and result.get("selected_incident")
            ):
                return {
                    **result,
                    "attempts": attempt,
                }

        if attempt < MAX_HISTORY_ATTEMPTS:
            time.sleep(HISTORY_RETRY_DELAY_SECONDS)

    return {
        **(last_result or {}),
        "attempts": MAX_HISTORY_ATTEMPTS,
    }


def _build_investigation_prompt(
    event: dict,
    selected_incident: dict,
) -> str:
    """
    Build the Sentinel investigation prompt from a validated event
    and canonical incident.
    """

    detail = event.get("detail", {})
    state = detail.get("state", {})
    previous_state = detail.get("previousState", {})

    event_id = event.get("id")
    event_time = event.get("time")

    alarm_name = detail.get("alarmName")
    previous_value = previous_state.get("value")
    current_state = state.get("value")
    state_reason = state.get("reason")

    incident_timestamp = selected_incident["timestamp"]

    return f"""
An EventBridge CloudWatch alarm state-change event has triggered
Sentinel.

EVENT:
{json.dumps(event, indent=2)}

Event metadata:
- Event ID: {event_id}
- Event time: {event_time}
- Alarm name: {alarm_name}
- Previous state: {previous_value}
- Current state: {current_state}
- State reason: {state_reason}

A deterministic alarm-history lookup identified the canonical incident.

CANONICAL INCIDENT:
{json.dumps(selected_incident, indent=2)}

Canonical incident timestamp:

{incident_timestamp}

IMPORTANT:

The EventBridge timestamp is trigger metadata only.

Use the canonical incident timestamp returned by alarm history
for the investigation.

Do not replace it with the EventBridge event timestamp.

For historical ECS investigation:
- call get_ecs_task_at_time() using the canonical incident timestamp;
- if it identifies a candidate task, use that task ID for
  get_ecs_metrics();
- never substitute the currently running ECS task.

Perform read-only investigation only.
Do not perform remediation.

Produce exactly ONE concise investigation report.

Do not include analysis outside the final report.
Do not repeat, restate, or regenerate the report.
Your response must end after the final conclusion.
"""


def _build_revision_function(
    incident_timestamp: str,
):
    """
    Build the bounded-revision callback used by the shared review
    pipeline.
    """

    def regenerate(feedback: str) -> str:
        revision_prompt = f"""
Revise the previous Sentinel investigation report.

The canonical incident timestamp remains:

{incident_timestamp}

Reviewer feedback:

{feedback}

Rules:

- Use only evidence obtained during the investigation.
- Do not invent evidence.
- Preserve established observations.
- Do not turn correlation into causation.
- Preserve ROOT CAUSE: UNCONFIRMED when causality remains unproven.
- Do not infer endpoint behavior from its name or path.
- Do not infer infrastructure changes from missing CloudTrail events.
- Do not substitute current ECS state for historical task evidence.
- Produce exactly ONE final report.
- Do not include analysis outside the report.

Return only the revised report.
"""

        return investigate(revision_prompt)

    return regenerate


def handle_event(event: dict) -> dict:
    """
    Process an EventBridge CloudWatch alarm event.

    This function is transport-agnostic and can be called by both
    the local CLI entrypoint and AWS Lambda.
    """

    if not isinstance(event, dict):
        raise ValueError(
            "EventBridge event must be a JSON object."
        )

    detail = event.get("detail", {})

    alarm_name = detail.get("alarmName")

    state = detail.get("state", {})
    previous_state = detail.get("previousState", {})

    current_state = state.get("value")
    previous_value = previous_state.get("value")
    state_reason = state.get("reason")

    event_time = event.get("time")
    event_id = event.get("id")

    base_result = {
        "event_id": event_id,
        "alarm_name": alarm_name,
        "event_time": event_time,
        "previous_state": previous_value,
        "current_state": current_state,
        "state_reason": state_reason,
    }

    if current_state != "ALARM":
        return {
            **base_result,
            "status": "ignored",
            "message": (
                f"Alarm event ignored because current state is "
                f"{current_state!r}, not 'ALARM'."
            ),
            "attempts": 0,
            "incident": None,
            "report": None,
        }

    history_result = _get_selected_incident_with_retry()

    if history_result.get("status") != "success":
        slack_status = "not_attempted"

        try:
            send_slack_message(
                "🚨 Sentinel Investigation\n\n"
                f"Alarm: {alarm_name}\n"
                f"Event: {event_id}\n\n"
                "Status: BLOCKED\n"
                "No canonical incident was identified from "
                "alarm history after bounded retries.\n\n"
                "Sentinel did not invent an incident timestamp."
            )
            slack_status = "delivered"

        except Exception as exc:
            slack_status = "failed"

            print(
                "Slack notification failed: "
                f"{type(exc).__name__}: {exc}"
            )

        return {
            **base_result,
            "status": "blocked",
            "message": (
                "No canonical incident was identified from alarm "
                "history after bounded retries."
            ),
            "attempts": history_result.get(
                "attempts",
                MAX_HISTORY_ATTEMPTS,
            ),
            "incident": None,
            "report": None,
            "history_result": history_result,
            "slack_status": slack_status,
        }

    selected_incident = history_result.get(
        "selected_incident"
    )

    if not selected_incident:
        slack_status = "not_attempted"

        try:
            send_slack_message(
                "🚨 Sentinel Investigation\n\n"
                f"Alarm: {alarm_name}\n"
                f"Event: {event_id}\n\n"
                "Status: BLOCKED\n"
                "No canonical incident was identified from "
                "alarm history.\n\n"
                "Sentinel did not invent an incident timestamp."
            )
            slack_status = "delivered"

        except Exception as exc:
            slack_status = "failed"
            print(
                "Slack notification failed: "
                f"{type(exc).__name__}: {exc}"
            )

        return {
            **base_result,
            "status": "blocked",
            "message": (
                "Alarm history lookup completed successfully, but "
                "no selected incident was returned."
            ),
            "attempts": history_result.get(
                "attempts",
                1,
            ),
            "incident": None,
            "report": None,
            "history_result": history_result,
            "slack_status": slack_status,
        }

    incident_timestamp = selected_incident.get("timestamp")

    if not incident_timestamp:
        return {
            **base_result,
            "status": "blocked",
            "message": (
                "Alarm history returned a selected incident without "
                "a canonical incident timestamp."
            ),
            "attempts": history_result.get(
                "attempts",
                1,
            ),
            "incident": selected_incident,
            "report": None,
            "history_result": history_result,
        }

    try:
        investigation_prompt = _build_investigation_prompt(
            event,
            selected_incident,
        )

        initial_report = investigate(
            investigation_prompt
        )

        evidence = {
            "event": event,
            "alarm_history": history_result,
            "selected_incident": selected_incident,
        }

        pipeline_result = review_and_revise(
            report=initial_report,
            evidence=evidence,
            regenerate=_build_revision_function(
                incident_timestamp
            ),
        )
        report = pipeline_result["report"]

        slack_status = "not_attempted"

        try:
            send_slack_message(
                "🚨 Sentinel Investigation\n\n"
                f"Alarm: {alarm_name}\n"
                f"Incident: {incident_timestamp}\n\n"
                f"{report}"
            )
            slack_status = "delivered"

        except Exception as exc:
            slack_status = "failed"
            print(
                "Slack notification failed: "
                f"{type(exc).__name__}: {exc}"
            )

    except Exception as exc:
        return {
            **base_result,
            "status": "blocked",
            "message": (
                "Sentinel investigation or review pipeline failed: "
                f"{type(exc).__name__}: {exc}"
            ),
            "attempts": history_result.get(
                "attempts",
                1,
            ),
            "incident": selected_incident,
            "report": None,
        }

    return {
        **base_result,
        "status": "success",
        "message": (
            "Sentinel investigation and review completed."
        ),
        "attempts": history_result.get(
            "attempts",
            1,
        ),
        "incident": selected_incident,
        "report": report,
        "review": pipeline_result["review"],
        "review_status": pipeline_result["review_status"],
        "revision_count": pipeline_result["revision_count"],
        "slack_status": slack_status,
    }


def lambda_handler(event, context):
    """
    AWS Lambda entrypoint for EventBridge.

    EventBridge invokes this function with the complete event object.
    """

    result = handle_event(event)

    print(
        json.dumps(
            result,
            indent=2,
            default=str,)
        )

    return result
def main() -> None:
    """
    Local EventBridge test entrypoint.

    Reads a complete EventBridge JSON event from stdin.
    """

    raw_event = sys.stdin.read().strip()

    if not raw_event:
        raise ValueError(
            "No EventBridge event was provided on stdin."
        )

    try:
        event = json.loads(raw_event)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON EventBridge event: {exc}"
        ) from exc

    result = lambda_handler(
        event,
        None,
    )

    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()