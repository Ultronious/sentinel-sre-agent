import json
import os
from pathlib import Path

from strands import Agent
from strands.models.openai import OpenAIModel

from agent.reviewer import review_report


BASE_DIR = Path(__file__).resolve().parent
CASES_FILE = BASE_DIR / "cases.json"
FIXTURES_DIR = BASE_DIR / "fixtures"

MAX_REVISIONS = 2


SENTINEL_EVAL_PROMPT = """
You are Sentinel, an AWS SRE investigation agent being evaluated against
a fixed evidence fixture.

The fixture contains the complete available evidence for this scenario.

Rules:
- Use only the supplied evidence.
- Do not call tools.
- Do not invent evidence.
- Distinguish observed facts, correlations, hypotheses, and unknowns.
- Temporal or quantitative correlation alone does not establish causation.
- Do not infer endpoint behavior from its name, path, method, or status.
- Do not infer that missing CloudTrail events prove that no infrastructure
  change occurred.
- Do not substitute current ECS state for historical evidence.
- If causality is not directly established, state:

ROOT CAUSE: UNCONFIRMED

Produce exactly one concise investigation report.
"""


model = OpenAIModel(
    client_args={
        "api_key": os.environ["OPENAI_API_KEY"],
        "base_url": "https://bedrock-mantle.us-east-1.api.aws/v1",
    },
    model_id="zai.glm-5",
)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def extract_text(response) -> str:
    """
    Extract the assistant's final text from a Strands AgentResult.
    """

    return response.message["content"][0]["text"]


def evaluate_report(report: str, expected: dict) -> dict:
    """
    Deterministic evaluation of the generated report.
    """

    report_lower = report.lower()

    must_contain = expected.get("must_contain", [])
    must_not_contain = expected.get("must_not_contain", [])

    missing = [
        phrase
        for phrase in must_contain
        if phrase.lower() not in report_lower
    ]

    forbidden = [
        phrase
        for phrase in must_not_contain
        if phrase.lower() in report_lower
    ]

    return {
        "passed": not missing and not forbidden,
        "missing": missing,
        "forbidden": forbidden,
    }


def run_sentinel(
    fixture: dict,
    revision_feedback: str = "",
) -> str:
    """
    Run GLM-5 against a fixed evidence fixture.

    When revision_feedback is supplied, GLM-5 is asked to revise
    its previous report while continuing to use only the fixture.
    """

    revision_section = ""

    if revision_feedback:
        revision_section = f"""
A reviewer identified the following problems in the previous report:

REVIEW FEEDBACK:
{revision_feedback}

Revise the report to correct these issues.

Do not remove established evidence merely to satisfy the reviewer.
Do not invent replacement evidence.
Preserve uncertainty where causality remains unproven.
"""

    prompt = f"""
Investigate the following fixed AWS incident evidence.

Do not call external tools.
Use only the evidence supplied below.

EVIDENCE:
{json.dumps(fixture, indent=2)}

{revision_section}

Produce exactly one final investigation report.
"""

    sentinel = Agent(
        model=model,
        system_prompt=SENTINEL_EVAL_PROMPT,
    )

    response = sentinel(prompt)

    return extract_text(response)


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


def run_case(case: dict) -> dict:
    """
    Run one case through:

        GLM-5 draft
            ↓
        reviewer
            ↓
        bounded revision loop
            ↓
        deterministic evaluation
    """

    fixture_name = case["fixture"]
    fixture_path = FIXTURES_DIR / fixture_name
    fixture = load_json(fixture_path)

    print(f"\n[CASE] {case['name']}")
    print(f"Fixture: {fixture_name}")

    report = run_sentinel(fixture)

    revision_count = 0
    review_result = review_report(
        report=report,
        evidence=fixture,
    )

    while (
        review_result.get("verdict") == "REVISE"
        and revision_count < MAX_REVISIONS
    ):
        revision_count += 1

        print(
            f"Reviewer requested revision "
            f"({revision_count}/{MAX_REVISIONS})..."
        )

        feedback = format_review_feedback(review_result)

        report = run_sentinel(
            fixture,
            revision_feedback=feedback,
        )

        review_result = review_report(
            report=report,
            evidence=fixture,
        )

    if review_result.get("verdict") == "REVISE":
        review_status = "REJECTED_AFTER_MAX_REVISIONS"
    else:
        review_status = "PASS"

    evaluation = evaluate_report(
        report,
        case.get("expected", {}),
    )

    return {
        "name": case["name"],
        "fixture": fixture_name,
        "report": report,
        "review": review_result,
        "review_status": review_status,
        "revision_count": revision_count,
        "evaluation": evaluation,
    }


def main() -> None:
    cases = load_json(CASES_FILE)

    if not isinstance(cases, list):
        raise ValueError("cases.json must contain a list.")

    results = []

    print("Sentinel evaluation")
    print("===================")

    for case in cases:
        result = run_case(case)
        results.append(result)

        evaluation = result["evaluation"]
        review = result["review"]

        report_status = (
            "PASS"
            if evaluation["passed"]
            else "FAIL"
        )

        print(f"Report evaluation: {report_status}")
        print(
            f"Reviewer verdict: "
            f"{result['review_status']}"
        )
        print(
            f"Revisions used: "
            f"{result['revision_count']}"
        )

        if evaluation["missing"]:
            print(
                f"  Missing: {evaluation['missing']}"
            )

        if evaluation["forbidden"]:
            print(
                f"  Forbidden: {evaluation['forbidden']}"
            )

        if review.get("issues"):
            print(
                f"  Reviewer issues remaining: "
                f"{len(review['issues'])}"
            )

    draft_passed = sum(
        result["evaluation"]["passed"]
        for result in results
    )

    total = len(results)

    reviewer_passed = sum(
        result["review_status"] == "PASS"
        for result in results
    )

    print()
    print("===================")
    print("FINAL EVALUATION")
    print("===================")

    print(
        f"Final report score: "
        f"{draft_passed}/{total}"
    )

    if total:
        print(
            f"Final report percentage: "
            f"{(draft_passed / total) * 100:.1f}%"
        )

    print(
        f"Reviewer convergence: "
        f"{reviewer_passed}/{total}"
    )

    print()
    print("Case summary:")

    for result in results:
        print(
            f"- {result['name']}: "
            f"report="
            f"{'PASS' if result['evaluation']['passed'] else 'FAIL'}, "
            f"reviewer={result['review_status']}, "
            f"revisions={result['revision_count']}"
        )

        for issue in result["review"].get("issues", []):
            print(
                f"    {issue.get('severity', 'unknown').upper()}: "
                f"{issue.get('type', 'unknown')}"
            )


if __name__ == "__main__":
    main()