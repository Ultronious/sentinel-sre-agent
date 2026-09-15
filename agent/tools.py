import os

import boto3
from datetime import datetime, timedelta, timezone
import json
import re

from strands import tool


AWS_REGION = os.getenv(
    "AWS_REGION",
    os.getenv(
        "AWS_DEFAULT_REGION",
        "us-east-1",
    ),
)

AWS_PROFILE = os.getenv("AWS_PROFILE")

session_kwargs = {
    "region_name": AWS_REGION,
}

if AWS_PROFILE:
    session_kwargs["profile_name"] = AWS_PROFILE


aws_session = boto3.Session(
    **session_kwargs
)


logs = aws_session.client("logs")
ecs = aws_session.client("ecs")
cloudwatch = aws_session.client("cloudwatch")
cloudtrail = aws_session.client("cloudtrail")


def fetch_alarm_history(hours: int = 24) -> dict:
    """
    Deterministically retrieve and select the most recent
    OK -> ALARM transition for Sentinel.

    This is the reusable Python implementation.

    Strands exposes the same capability through get_alarm_history().
    Event-driven callers can use this function directly.

    Returns:
        A dictionary containing:
        - status
        - selected_incident
        - history
        - transition counts
    """

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    response = cloudwatch.describe_alarm_history(
        AlarmName="sentinel-high-latency",
        HistoryItemType="StateUpdate",
        StartDate=start_time,
        EndDate=end_time,
        MaxRecords=50,
    )

    history = []

    for item in response.get("AlarmHistoryItems", []):
        history_data = item.get("HistoryData")

        try:
            parsed_data = (
                json.loads(history_data)
                if history_data
                else None
            )
        except (TypeError, json.JSONDecodeError):
            parsed_data = None

        timestamp = item["Timestamp"].astimezone(timezone.utc)

        history.append(
            {
                "timestamp": timestamp.isoformat(),
                "history_type": item["HistoryItemType"],
                "summary": item["HistorySummary"],
                "data": parsed_data,
            }
        )

    history.sort(
        key=lambda item: item["timestamp"]
    )

    alarm_transitions = []

    for item in history:
        summary = item["summary"].upper()

        if (
            "OK -> ALARM" in summary
            or "OK TO ALARM" in summary
        ):
            alarm_transitions.append(item)

    if not alarm_transitions:
        return {
            "status": "no_incident",
            "alarm_name": "sentinel-high-latency",
            "window_hours": hours,
            "history_count": len(history),
            "alarm_transition_count": 0,
            "selected_incident": None,
            "history": history,
            "message": (
                "No OK -> ALARM transition was observed in the "
                "queried alarm-history window."
            ),
        }

    selected = alarm_transitions[-1]

    incident_timestamp = selected["timestamp"]
    metric_value = None
    threshold = None
    sample_count = None
    datapoint_timestamp = None

    data = selected.get("data") or {}

    new_state = data.get("newState") or {}
    reason_data = new_state.get("stateReasonData")

    if isinstance(reason_data, str):
        try:
            reason_data = json.loads(reason_data)
        except (TypeError, json.JSONDecodeError):
            reason_data = None

    if isinstance(reason_data, dict):
        threshold = reason_data.get("threshold")

        recent_datapoints = (
            reason_data.get("recentDatapoints") or []
        )

        if recent_datapoints:
            metric_value = recent_datapoints[-1]

        evaluated_datapoints = (
            reason_data.get("evaluatedDatapoints") or []
        )

        if evaluated_datapoints:
            triggering = evaluated_datapoints[-1]

            if isinstance(triggering, dict):
                metric_value = triggering.get(
                    "value",
                    metric_value,
                )

                sample_count = triggering.get(
                    "sampleCount",
                    sample_count,
                )

                datapoint_timestamp = triggering.get(
                    "timestamp"
                )

        if sample_count is None:
            sample_count = reason_data.get(
                "sampleCount"
            )

    if datapoint_timestamp:
        try:
            parsed_timestamp = datetime.fromisoformat(
                datapoint_timestamp.replace(
                    "Z",
                    "+00:00",
                )
            )

            incident_timestamp = (
                parsed_timestamp
                .astimezone(timezone.utc)
                .isoformat()
            )

        except (TypeError, ValueError):
            pass

    selected_incident = {
        "timestamp": incident_timestamp,
        "alarm_state_transition": "OK -> ALARM",
        "alarm_state_change_timestamp": selected["timestamp"],
        "metric": "TargetResponseTime",
        "value": metric_value,
        "threshold": threshold,
        "sample_count": sample_count,
        "history_summary": selected["summary"],
    }

    return {
        "status": "success",
        "alarm_name": "sentinel-high-latency",
        "window_hours": hours,
        "history_count": len(history),
        "alarm_transition_count": len(alarm_transitions),
        "selected_incident": selected_incident,
        "history": history,
    }


@tool
def get_alarm_history(hours: int = 24) -> dict:
    """
    Strands adapter around the deterministic alarm-history implementation.
    """

    return fetch_alarm_history(hours)


@tool
def get_alarm_state() -> dict:
    """
    Get the current state and reason for the Sentinel high-latency alarm.
    """

    response = cloudwatch.describe_alarms(
        AlarmNames=["sentinel-high-latency"]
    )

    alarms = response.get("MetricAlarms", [])

    if not alarms:
        return {
            "status": "error",
            "message": "sentinel-high-latency alarm was not found",
        }

    alarm = alarms[0]

    return {
        "status": "success",
        "alarm_name": alarm["AlarmName"],
        "state": alarm["StateValue"],
        "reason": alarm["StateReason"],
        "updated": alarm["StateUpdatedTimestamp"],
    }
@tool
def get_metrics(
    incident_time: str = "",
    before_minutes: int = 5,
    after_minutes: int = 5,
) -> dict:
    """
    Get ALB TargetResponseTime observations around a specific
    incident timestamp.
    """
    if incident_time:
        incident_dt = datetime.fromisoformat(
            incident_time.replace("Z", "+00:00")
        )

        start_time = incident_dt - timedelta(minutes=before_minutes)
        end_time = incident_dt + timedelta(minutes=after_minutes)

    else:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=60)

    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/ApplicationELB",
        MetricName="TargetResponseTime",
        Dimensions=[
            {
                "Name": "LoadBalancer",
                "Value": "app/sentinel-demo-alb/3e446915402d7462",
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=60,
        Statistics=["Average"],
    )

    datapoints = sorted(
        response.get("Datapoints", []),
        key=lambda point: point["Timestamp"],
    )

    return {
        "status": "success",
        "metric": "TargetResponseTime",
        "unit": "Seconds",
        "incident_time": incident_dt.isoformat() if incident_time else None,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "period_seconds": 60,
        "datapoint_count": len(datapoints),
        "datapoints": [
            {
                "timestamp": point["Timestamp"].isoformat(),
                "average_seconds": point["Average"],
            }
            for point in datapoints
        ],
    }
@tool
def query_logs(
    incident_time: str = "",
    before_minutes: int = 5,
    after_minutes: int = 5,
    max_events: int = 200,
) -> dict:
    """
    Query Sentinel application logs around a specific incident timestamp.

    Paginates CloudWatch log events up to a safety limit, extracts
    structured REQUEST_TELEMETRY fields, and returns a compact
    deterministic summary.
    """

    if incident_time:
        incident_dt = datetime.fromisoformat(
            incident_time.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

        start_time = incident_dt - timedelta(minutes=before_minutes)
        end_time = incident_dt + timedelta(minutes=after_minutes)

    else:
        incident_dt = None
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=15)

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    all_events = []
    next_token = None

    while len(all_events) < max_events:
        kwargs = {
            "logGroupName": "/ecs/sentinel-demo",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": min(50, max_events - len(all_events)),
        }

        if next_token:
            kwargs["nextToken"] = next_token

        response = logs.filter_log_events(**kwargs)

        page_events = response.get("events", [])

        if not page_events:
            break

        all_events.extend(page_events)

        new_next_token = response.get("nextToken")

        if not new_next_token or new_next_token == next_token:
            break

        next_token = new_next_token

    events = sorted(
        all_events[:max_events],
        key=lambda event: event["timestamp"],
    )

    telemetry_pattern = re.compile(
        r"REQUEST_TELEMETRY "
        r"method=(?P<method>\S+) "
        r"path=(?P<path>\S+) "
        r"status=(?P<status>\d+) "
        r"duration_ms=(?P<duration_ms>[0-9.]+)"
    )

    request_events = []
    other_event_count = 0

    for event in events:
        message = event["message"]

        match = telemetry_pattern.search(message)

        if match:
            request_events.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        event["timestamp"] / 1000,
                        tz=timezone.utc,
                    ).isoformat(),
                    "method": match.group("method"),
                    "path": match.group("path"),
                    "status": int(match.group("status")),
                    "duration_ms": float(
                        match.group("duration_ms")
                    ),
                }
            )
        else:
            other_event_count += 1

    durations = [
        event["duration_ms"]
        for event in request_events
    ]

    paths = {}

    for event in request_events:
        path = event["path"]

        if path not in paths:
            paths[path] = {
                "count": 0,
                "status_codes": {},
                "min_duration_ms": None,
                "max_duration_ms": None,
                "avg_duration_ms": None,
            }

        path_data = paths[path]

        path_data["count"] += 1

        status = str(event["status"])

        path_data["status_codes"][status] = (
            path_data["status_codes"].get(status, 0) + 1
        )

    for path, path_data in paths.items():
        path_durations = [
            event["duration_ms"]
            for event in request_events
            if event["path"] == path
        ]

        path_data["min_duration_ms"] = min(path_durations)
        path_data["max_duration_ms"] = max(path_durations)
        path_data["avg_duration_ms"] = (
            sum(path_durations) / len(path_durations)
        )

    telemetry_summary = {
        "request_count": len(request_events),
        "min_duration_ms": (
            min(durations)
            if durations
            else None
        ),
        "max_duration_ms": (
            max(durations)
            if durations
            else None
        ),
        "avg_duration_ms": (
            sum(durations) / len(durations)
            if durations
            else None
        ),
        "by_path": paths,
    }

    limit_reached = len(events) >= max_events

    return {
        "status": "success",
        "log_group": "/ecs/sentinel-demo",
        "incident_time": (
            incident_dt.isoformat()
            if incident_dt
            else None
        ),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "event_count": len(events),
        "request_telemetry_summary": telemetry_summary,
        "other_event_count": other_event_count,
        "coverage_warning": limit_reached,
        "coverage_reason": (
            "Maximum event collection limit reached; "
            "results may be incomplete."
            if limit_reached
            else "All available events in the queried window were collected."
        ),
    }


@tool
def inspect_ecs_task() -> dict:
    """
    Inspect the currently running Sentinel demo ECS task.
    """
    response = ecs.list_tasks(
        cluster="sentinel-cluster",
        desiredStatus="RUNNING",
        launchType="FARGATE",
    )

    task_arns = response.get("taskArns", [])

    if not task_arns:
        return {
            "status": "success",
            "running_tasks": 0,
            "message": "No running Fargate tasks found.",
        }

    tasks = ecs.describe_tasks(
        cluster="sentinel-cluster",
        tasks=task_arns,
    )["tasks"]

    return {
        "status": "success",
        "running_tasks": len(tasks),
        "tasks": [
            {
                "task_arn": task["taskArn"],
                "last_status": task["lastStatus"],
                "task_definition": task["taskDefinitionArn"],
                "cpu": task.get("cpu"),
                "memory": task.get("memory"),
                "launch_type": task.get("launchType"),
                "availability_zone": task.get("availabilityZone"),
            }
            for task in tasks
        ],
    }
@tool
def get_ecs_lifecycle_events(
    incident_time: str = "",
    before_minutes: int = 5,
    after_minutes: int = 5,
) -> dict:
    """
    Get ECS RunTask and StopTask CloudTrail events around
    a specific incident timestamp.

    Extracts task ARNs from CloudTrail events when available.
    """

    if incident_time:
        incident_dt = datetime.fromisoformat(
            incident_time.replace("Z", "+00:00")
        )

        start_time = incident_dt - timedelta(minutes=before_minutes)
        end_time = incident_dt + timedelta(minutes=after_minutes)

    else:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=6)

    events = []

    for event_name in ["RunTask", "StopTask"]:
        response = cloudtrail.lookup_events(
            LookupAttributes=[
                {
                    "AttributeKey": "EventName",
                    "AttributeValue": event_name,
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
            MaxResults=50,
        )

        for event in response.get("Events", []):
            event_record = {
                "event_name": event["EventName"],
                "event_time": event["EventTime"].isoformat(),
                "event_id": event["EventId"],
                "username": event.get("Username"),
            }

            # CloudTrail stores the full event payload as JSON.
            # Extract task ARNs when available.
            cloudtrail_event = event.get("CloudTrailEvent")

            if cloudtrail_event:
                try:
                    cloudtrail_data = json.loads(cloudtrail_event)

                    request_parameters = cloudtrail_data.get(
                        "requestParameters",
                        {},
                    )

                    response_elements = cloudtrail_data.get(
                        "responseElements",
                        {},
                    )

                    task_arns = []

                    # RunTask response contains tasks[].taskArn
                    for task in response_elements.get("tasks", []) or []:
                        task_arn = task.get("taskArn")

                        if task_arn:
                            task_arns.append(task_arn)

                    # StopTask request contains the task ARN.
                    task = request_parameters.get("task")

                    if task:
                        task_arns.append(task)

                    if task_arns:
                        event_record["task_arns"] = list(dict.fromkeys(task_arns))

                except (TypeError, json.JSONDecodeError):
                    pass

            events.append(event_record)

    events.sort(key=lambda event: event["event_time"])

    return {
        "status": "success",
        "incident_time": incident_dt.isoformat() if incident_time else None,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "event_count": len(events),
        "events": events,
        "interpretation": (
            "No RunTask or StopTask events were observed in the queried "
            "CloudTrail window. This does not establish that no deployment, "
            "scaling, configuration change, or other infrastructure change "
            "occurred."
        ),
    }

@tool
def get_ecs_metrics(
    incident_time: str = "",
    before_minutes: int = 5,
    after_minutes: int = 5,
    task_id: str = "",
) -> dict:
    """
    Get ECS CPU and memory utilization around an incident timestamp.

    Returns both the observed datapoints and a deterministic
    incident-relative summary so the agent does not need to calculate
    baseline, incident, and after values itself.
    """

    if incident_time:
        incident_dt = datetime.fromisoformat(
            incident_time.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

        start_time = incident_dt - timedelta(minutes=before_minutes)
        end_time = incident_dt + timedelta(minutes=after_minutes)

    else:
        incident_dt = None
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=60)

    if not task_id:
        if incident_dt is not None:
            return {
                "status": "insufficient_evidence",
                "message": "No historical ECS task ID was supplied.",
                "incident_time": incident_dt.isoformat(),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "task_id": None,
                "metrics": {},
                "interpretation": (
                    "A historical incident was supplied without a task ID. "
                    "Current running tasks were not substituted because they "
                    "may not represent the task active during the incident."
                ),
            }

        task_response = ecs.list_tasks(
            cluster="sentinel-cluster",
            desiredStatus="RUNNING",
            launchType="FARGATE",
        )

        task_arns = task_response.get("taskArns", [])

        if not task_arns:
            return {
                "status": "success",
                "message": "No running Fargate task found.",
                "incident_time": None,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "task_id": None,
                "metrics": {},
                "interpretation": (
                    "No currently running Fargate task was found."
                ),
            }

        task_id = task_arns[0].split("/")[-1]

    else:
        task_id = task_id.split("/")[-1]

    dimensions = [
        {
            "Name": "TaskId",
            "Value": task_id,
        },
        {
            "Name": "ClusterName",
            "Value": "sentinel-cluster",
        },
        {
            "Name": "TaskDefinitionFamily",
            "Value": "sentinel-demo",
        },
    ]

    metric_definitions = [
        ("TaskCpuUtilization", "Percent"),
        ("TaskMemoryUtilization", "Percent"),
    ]

    metrics = {}

    for metric_name, unit in metric_definitions:
        response = cloudwatch.get_metric_statistics(
            Namespace="ECS/ContainerInsights",
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=["Average"],
        )

        datapoints = sorted(
            response.get("Datapoints", []),
            key=lambda point: point["Timestamp"],
        )

        normalized_datapoints = [
            {
                "timestamp": point["Timestamp"]
                .astimezone(timezone.utc)
                .isoformat(),
                "average": point["Average"],
            }
            for point in datapoints
        ]

        summary = {
            "before": None,
            "incident": None,
            "after": None,
        }

        if incident_dt and normalized_datapoints:
            incident_points = [
                point
                for point in normalized_datapoints
                if point["timestamp"][:16]
                == incident_dt.isoformat()[:16]
            ]

            before_points = [
                point
                for point in normalized_datapoints
                if point["timestamp"] < incident_dt.isoformat()
            ]

            after_points = [
                point
                for point in normalized_datapoints
                if point["timestamp"] > incident_dt.isoformat()
            ]

            if before_points:
                summary["before"] = before_points[-1]

            if incident_points:
                summary["incident"] = incident_points[0]

            if after_points:
                summary["after"] = after_points[0]

        metrics[metric_name] = {
            "unit": unit,
            "datapoint_count": len(normalized_datapoints),
            "summary": summary,
            "datapoints": normalized_datapoints,
        }

    return {
        "status": "success",
        "incident_time": (
            incident_dt.isoformat()
            if incident_dt
            else None
        ),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "task_id": task_id,
        "cluster": "sentinel-cluster",
        "task_definition_family": "sentinel-demo",
        "metrics": metrics,
        "interpretation": (
            "The summary is derived deterministically from the returned "
            "CloudWatch datapoints. 'Before' is the latest datapoint before "
            "the incident timestamp, 'incident' is the datapoint matching "
            "the incident minute, and 'after' is the first datapoint after "
            "the incident timestamp. Missing datapoints must not be "
            "interpreted as normal or insignificant utilization."
        ),
    }
@tool
def get_ecs_task_at_time(
    incident_time: str,
    before_minutes: int = 5,
    after_minutes: int = 5,
) -> dict:
    """
    Identify ECS task candidates with Container Insights activity
    overlapping an incident timestamp.

    Historical task attribution is based on observed task-level
    Container Insights datapoints. This does not by itself prove
    that the task served the affected request.
    """

    incident_dt = datetime.fromisoformat(
        incident_time.replace("Z", "+00:00")
    ).astimezone(timezone.utc)

    start_time = incident_dt - timedelta(minutes=before_minutes)
    end_time = incident_dt + timedelta(minutes=after_minutes)

    metrics_response = cloudwatch.list_metrics(
        Namespace="ECS/ContainerInsights",
        MetricName="TaskCpuUtilization",
        Dimensions=[
            {
                "Name": "ClusterName",
                "Value": "sentinel-cluster",
            }
        ],
    )

    candidates = []

    for metric in metrics_response.get("Metrics", []):
        dimensions = {
            dimension["Name"]: dimension["Value"]
            for dimension in metric.get("Dimensions", [])
        }

        task_id = dimensions.get("TaskId")
        cluster_name = dimensions.get("ClusterName")
        task_definition_family = dimensions.get(
            "TaskDefinitionFamily"
        )

        if not task_id:
            continue

        if cluster_name != "sentinel-cluster":
            continue

        if task_definition_family != "sentinel-demo":
            continue

        task_dimensions = [
            {
                "Name": "TaskId",
                "Value": task_id,
            },
            {
                "Name": "ClusterName",
                "Value": "sentinel-cluster",
            },
            {
                "Name": "TaskDefinitionFamily",
                "Value": "sentinel-demo",
            },
        ]

        cpu_response = cloudwatch.get_metric_statistics(
            Namespace="ECS/ContainerInsights",
            MetricName="TaskCpuUtilization",
            Dimensions=task_dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=["Average"],
        )

        datapoints = sorted(
            cpu_response.get("Datapoints", []),
            key=lambda point: point["Timestamp"],
        )

        if not datapoints:
            continue

        normalized = [
            {
                "timestamp": point["Timestamp"]
                .astimezone(timezone.utc)
                .isoformat(),
                "average": point["Average"],
            }
            for point in datapoints
        ]

        incident_points = [
            point
            for point in normalized
            if point["timestamp"][:16]
            == incident_dt.isoformat()[:16]
        ]

        if not incident_points:
            continue

        incident_point = incident_points[0]

        before_points = [
            point
            for point in normalized
            if point["timestamp"] < incident_dt.isoformat()
        ]

        after_points = [
            point
            for point in normalized
            if point["timestamp"] > incident_dt.isoformat()
        ]

        candidates.append(
            {
                "task_id": task_id,
                "task_definition_family": task_definition_family,
                "evidence": {
                    "metric": "TaskCpuUtilization",
                    "incident_minute_observed": True,
                    "incident": incident_point,
                    "before": (
                        before_points[-1]
                        if before_points
                        else None
                    ),
                    "after": (
                        after_points[0]
                        if after_points
                        else None
                    ),
                },
            }
        )

    if not candidates:
        return {
            "status": "insufficient_evidence",
            "incident_time": incident_dt.isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "candidates": [],
            "attribution_status": "no_task_confirmed",
            "interpretation": (
                "No task-level Container Insights CPU datapoint "
                "was observed at the incident minute for a "
                "discovered sentinel-demo task. This does not "
                "establish that no task was active."
            ),
        }

    return {
        "status": "success",
        "incident_time": incident_dt.isoformat(),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "candidates": candidates,
        "attribution_status": "inferred_from_container_insights",
        "interpretation": (
            "Candidates had observed TaskCpuUtilization activity "
            "at the incident minute. This indicates Container "
            "Insights activity for those task IDs but does not independently prove that a candidate served the affected ALB request."
        ),
    }