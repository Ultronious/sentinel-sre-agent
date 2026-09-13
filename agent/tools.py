import boto3
from strands import tool
from datetime import datetime, timedelta, timezone
import json
import re

logs = boto3.Session(
    profile_name="sentinel",
    region_name="us-east-1",
).client("logs")

ecs = boto3.Session(
    profile_name="sentinel",
    region_name="us-east-1",
).client("ecs")

cloudwatch = boto3.Session(
    profile_name="sentinel",
    region_name="us-east-1",
).client("cloudwatch")

cloudtrail = boto3.Session(
    profile_name="sentinel",
    region_name="us-east-1",
).client("cloudtrail")

@tool
def get_alarm_history(hours: int = 24) -> dict:
    """
    Get recent state transitions for the Sentinel high-latency alarm.
    Used to locate when an incident actually occurred.
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
            parsed_data = json.loads(history_data) if history_data else None
        except (TypeError, json.JSONDecodeError):
            parsed_data = None

        history.append(
            {
                "timestamp": item["Timestamp"].isoformat(),
                "history_type": item["HistoryItemType"],
                "summary": item["HistorySummary"],
                "data": parsed_data,
            }
        )

    history.sort(key=lambda item: item["timestamp"])

    return {
        "status": "success",
        "alarm_name": "sentinel-high-latency",
        "window_hours": hours,
        "history_count": len(history),
        "history": history,
    }
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
) -> dict:
    """
    Query Sentinel application logs around a specific incident timestamp.

    Extracts structured REQUEST_TELEMETRY fields when present while
    preserving raw messages for other log events.
    """
    if incident_time:
        incident_dt = datetime.fromisoformat(
            incident_time.replace("Z", "+00:00")
        )

        start_time = incident_dt - timedelta(minutes=before_minutes)
        end_time = incident_dt + timedelta(minutes=after_minutes)

    else:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=15)

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    response = logs.filter_log_events(
        logGroupName="/ecs/sentinel-demo",
        startTime=start_ms,
        endTime=end_ms,
        limit=50,
    )

    events = sorted(
        response.get("events", []),
        key=lambda event: event["timestamp"],
    )

    parsed_events = []

    telemetry_pattern = re.compile(
        r"REQUEST_TELEMETRY "
        r"method=(?P<method>\S+) "
        r"path=(?P<path>\S+) "
        r"status=(?P<status>\d+) "
        r"duration_ms=(?P<duration_ms>[0-9.]+)"
    )

    for event in events:
        timestamp = datetime.fromtimestamp(
            event["timestamp"] / 1000,
            tz=timezone.utc,
        ).isoformat()

        message = event["message"]

        match = telemetry_pattern.search(message)

        if match:
            parsed_events.append(
                {
                    "timestamp": timestamp,
                    "type": "request_telemetry",
                    "method": match.group("method"),
                    "path": match.group("path"),
                    "status": int(match.group("status")),
                    "duration_ms": float(match.group("duration_ms")),
                    "log_stream": event.get("logStreamName"),
                    "raw_message": message,
                }
            )
        else:
            parsed_events.append(
                {
                    "timestamp": timestamp,
                    "type": "log",
                    "message": message,
                    "log_stream": event.get("logStreamName"),
                }
            )
        request_events = [
        event
        for event in parsed_events
        if event["type"] == "request_telemetry"
    ]

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
                "durations_ms": [],
                "status_codes": {},
            }

        paths[path]["count"] += 1
        paths[path]["durations_ms"].append(event["duration_ms"])

        status = str(event["status"])
        paths[path]["status_codes"][status] = (
            paths[path]["status_codes"].get(status, 0) + 1
        )

    for path_data in paths.values():
        path_data["min_duration_ms"] = min(path_data["durations_ms"])
        path_data["max_duration_ms"] = max(path_data["durations_ms"])
        path_data["avg_duration_ms"] = (
            sum(path_data["durations_ms"])
            / len(path_data["durations_ms"])
        )

        del path_data["durations_ms"]

    telemetry_summary = {
        "request_count": len(request_events),
        "min_duration_ms": min(durations) if durations else None,
        "max_duration_ms": max(durations) if durations else None,
        "avg_duration_ms": (
            sum(durations) / len(durations)
            if durations
            else None
        ),
        "by_path": paths,
    }

    return {
        "status": "success",
        "log_group": "/ecs/sentinel-demo",
        "incident_time": incident_dt.isoformat() if incident_time else None,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "event_count": len(parsed_events),
        "request_telemetry_summary": telemetry_summary,
        "events": parsed_events,
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

    If a historical task_id is provided, query metrics specifically for
    that task. For historical incidents, callers should prefer a task ID
    whose lifetime overlaps the incident window rather than relying on
    the currently running task.
    """

    if incident_time:
        incident_dt = datetime.fromisoformat(
            incident_time.replace("Z", "+00:00")
        )

        start_time = incident_dt - timedelta(minutes=before_minutes)
        end_time = incident_dt + timedelta(minutes=after_minutes)

    else:
        incident_dt = None
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=60)

    if not task_id:
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
                "metrics": {},
                "interpretation": (
                    "No historical task ID was supplied and no currently "
                    "running Fargate task was found."
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

        metrics[metric_name] = {
            "unit": unit,
            "datapoint_count": len(datapoints),
            "datapoints": [
                {
                    "timestamp": point["Timestamp"].isoformat(),
                    "average": point["Average"],
                }
                for point in datapoints
            ],
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
            "Metrics represent only datapoints returned for the queried "
            "task and time window. Missing datapoints mean utilization "
            "could not be observed for that window. Missing datapoints "
            "must not be interpreted as low, normal, or insignificant "
            "utilization."
        ),
    }