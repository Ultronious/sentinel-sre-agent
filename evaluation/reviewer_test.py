import json

from agent.reviewer import (
    deterministic_review,
    review_report,
)


EVIDENCE = {
    "incident_time": "2026-09-13T11:51:00+00:00",
    "alb_target_response_time_seconds": 2.001781,
    "request": {
        "path": "/slow",
        "status": 200,
        "duration_ms": 2000.59,
    },
    "ecs": {
        "cpu_before": 0.235,
        "cpu_incident": 0.265,
        "cpu_after": 0.234,
        "memory_incident": 6.64,
    },
    "task_attribution": {
        "task_id": "e7e686ca2ce24f29a98c35e85b3bbf06",
        "status": "inferred_from_container_insights",
    },
    "cloudtrail": {
        "run_task_events": 0,
        "stop_task_events": 0,
        "interpretation": (
            "No RunTask or StopTask events were observed. "
            "This does not prove that no deployment, scaling, "
            "replacement, or configuration change occurred."
        ),
    },
}


BAD_REPORT = """
The latency breach was caused by a single request to the /slow endpoint.

The /slow endpoint intentionally sleeps for two seconds.

CPU and memory were normal, so no resource pressure occurred.

No deployment or scaling occurred.

The current running ECS task handled the request.

ROOT CAUSE: UNCONFIRMED
"""


CLEAN_REPORT = """
INCIDENT
The sentinel-high-latency incident was selected at
2026-09-13T11:51:00+00:00. TargetResponseTime was 2.001781 seconds.

OBSERVED EVIDENCE
Application telemetry recorded one /slow request with duration
2000.59 ms. ECS CPU utilization was 0.235% before, 0.265% at the
incident, and 0.234% after. Memory was 6.64% at the incident.

The historical task candidate was
e7e686ca2ce24f29a98c35e85b3bbf06, with attribution inferred from
Container Insights activity at the incident minute.

CORRELATIONS
The /slow request is temporally and quantitatively correlated with
the elevated TargetResponseTime datapoint. CPU and memory did not
show a corresponding increase.

LIFECYCLE EVIDENCE
No RunTask or StopTask events were observed in the queried CloudTrail
window. This does not prove that no deployment, scaling, replacement,
or configuration change occurred.

STRONGEST HYPOTHESIS
The /slow request is the strongest correlated factor associated with
the latency spike.

MISSING EVIDENCE
No direct trace links the specific application request to the ALB
metric datapoint. The internal mechanism responsible for the request
latency is not established.

VALIDATION STATUS
Causation is not established by the available evidence.

FINAL CONCLUSION
ROOT CAUSE: UNCONFIRMED
The /slow request is strongly correlated with the observed latency
spike, but the causal mechanism remains unvalidated.
"""


def run_bad_report_test():
    print("=" * 60)
    print("TEST 1: DETERMINISTIC HARD-RULE GATE")
    print("=" * 60)

    issues = deterministic_review(BAD_REPORT)

    print(json.dumps(issues, indent=2))

    if issues:
        print("\nRESULT: REVISE")
        print("PASS: Hard-rule gate correctly rejected the bad report.")
        return True

    print("\nRESULT: PASS")
    print("FAIL: Hard-rule gate failed to detect the bad report.")
    return False


def run_clean_report_test():
    print()
    print("=" * 60)
    print("TEST 2: GLM-4.7 SEMANTIC REVIEW")
    print("=" * 60)

    hard_issues = deterministic_review(CLEAN_REPORT)

    if hard_issues:
        print("FAIL: Clean report was rejected by deterministic checks.")
        print(json.dumps(hard_issues, indent=2))
        return False

    print("Deterministic gate: PASS")
    print("Sending clean report to GLM-4.7...")

    result = review_report(
        report=CLEAN_REPORT,
        evidence=EVIDENCE,
    )

    print("\nGLM-4.7 review:")
    print(json.dumps(result, indent=2))

    verdict = result.get("verdict")

    if verdict == "PASS":
        print("\nPASS: Reviewer accepted the clean report.")
        return True

    print("\nREVISE: Reviewer found issues in the clean report.")
    return False


def main():
    bad_passed = run_bad_report_test()
    clean_passed = run_clean_report_test()

    print()
    print("=" * 60)
    print("REVIEWER TEST SUMMARY")
    print("=" * 60)
    print(f"Hard-rule rejection test: {'PASS' if bad_passed else 'FAIL'}")
    print(f"Semantic reviewer test:    {'PASS' if clean_passed else 'FAIL'}")

    total_passed = sum(
        [bad_passed, clean_passed]
    )

    print(f"\nResult: {total_passed}/2 tests passed.")


if __name__ == "__main__":
    main()