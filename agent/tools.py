import boto3
from strands import tool
from datetime import datetime, timedelta, timezone

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
def get_metrics(minutes: int = 15) -> dict:
    """
    Get recent ALB TargetResponseTime observations for the Sentinel demo.
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
        "period_seconds": 60,
        "datapoints": [
            {
                "timestamp": point["Timestamp"].isoformat(),
                "average_seconds": point["Average"],
            }
            for point in datapoints
        ],
    }