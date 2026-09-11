import boto3
from strands import tool


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