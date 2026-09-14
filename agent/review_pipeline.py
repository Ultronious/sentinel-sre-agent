from collections.abc import Callable

from agent.reviewer import review_report


MAX_REVISIONS = 2


def format_review_feedback(review: dict) -> str:
    """
    Convert reviewer findings into a compact revision instruction.
    """

    issues = review.get("issues", [])

    if not issues:
        return review.get("summary", "")

    lines = []

    for index, issue in enumerate(issues, start=1):
        issue_type = issue.get("type", "unknown")
        severity = issue.get("severity", "unknown")
        claim = issue.get("claim", "")
        reason = issue.get("reason", "")

        lines.append(
            f"{index}. [{severity.upper()}] {issue_type}\n"
            f"   Problematic claim: {claim}\n"
            f"   Reason: {reason}"
        )

    return "\n".join(lines)


def review_and_revise(
    report: str,
    evidence: dict,
    regenerate: Callable[[str], str],
    max_revisions: int = MAX_REVISIONS,
) -> dict:
    """
    Run the shared reviewer + bounded revision loop.

    Args:
        report:
            Initial investigation report.

        evidence:
            Fixed evidence against which the report is reviewed.

        regenerate:
            Callable that receives reviewer feedback and returns
            a revised report.

        max_revisions:
            Maximum number of revision attempts.

    Returns:
        Dictionary containing:
        - report
        - review
        - review_status
        - revision_count
    """

    revision_count = 0

    review_result = review_report(
        report=report,
        evidence=evidence,
    )

    while (
        review_result.get("verdict") == "REVISE"
        and revision_count < max_revisions
    ):
        revision_count += 1

        feedback = format_review_feedback(
            review_result
        )

        report = regenerate(feedback)

        review_result = review_report(
            report=report,
            evidence=evidence,
        )

    if review_result.get("verdict") == "REVISE":
        review_status = "REJECTED_AFTER_MAX_REVISIONS"
    else:
        review_status = "PASS"

    return {
        "report": report,
        "review": review_result,
        "review_status": review_status,
        "revision_count": revision_count,
    }