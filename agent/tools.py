import boto3
from strands import tool
from datetime import datetime, timedelta, timezone

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
def get_metrics(minutes: int = 60) -> dict:
    """
    Get ALB TargetResponseTime observations for the Sentinel demo
    over a historical investigation window.
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=minutes)

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
        "window_minutes": minutes,
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
def query_logs(minutes: int = 15) -> dict:
    """
    Query recent Sentinel demo application logs from CloudWatch Logs.
    Returns log events from the last specified number of minutes.
    """
    import time

    end_time = int(time.time() * 1000)
    start_time = end_time - (minutes * 60 * 1000)

    response = logs.filter_log_events(
        logGroupName="/ecs/sentinel-demo",
        startTime=start_time,
        endTime=end_time,
        limit=50,
    )

    events = response.get("events", [])

    return {
        "status": "success",
        "log_group": "/ecs/sentinel-demo",
        "window_minutes": minutes,
        "events": [
            {
                "timestamp": event["timestamp"],
                "message": event["message"],
                "log_stream": event["logStreamName"],
            }
            for event in events
        ],
        "event_count": len(events),
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