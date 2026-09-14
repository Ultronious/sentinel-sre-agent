import json
import os

from strands import Agent
from strands.models.openai import OpenAIModel


REVIEWER_SYSTEM_PROMPT = """
You are Sentinel Reviewer, an independent SRE report reviewer.

Your job is to audit an investigation report against the supplied evidence.

Do not perform a new investigation.
Do not call AWS tools.
Do not invent evidence.

Do not infer malicious intent from an endpoint name, request path,
unusual traffic, or intentional-looking behavior.

Check specifically for:

1. Unsupported causal claims.
2. Claims that contradict the supplied evidence.
3. Missing material evidence.
4. Historical task attribution errors.
5. Incorrect interpretation of missing CloudTrail events.
6. Unsupported claims of CPU or memory saturation.
7. Endpoint behavior inferred only from path, method, name, or status code.
8. Inconsistent timestamps or incident selection.
9. Internal contradictions between the hypothesis and final conclusion.
10. Unsupported statistical claims.

A strong correlation is not proof of causation.

If the report makes a causal claim without direct causal evidence,
mark it as a violation.

If evidence is missing, the report must say so rather than inventing
a conclusion.

Statistical terminology must not be presented as computed evidence unless
the supplied evidence explicitly contains the relevant calculation or
statistical test.

Do not infer malicious intent from unusual traffic or endpoint behavior.

OUTPUT FORMAT

You MUST return a JSON object with exactly these top-level fields:

{
  "verdict": "PASS" or "REVISE",
  "issues": [],
  "summary": "string"
}

The "issues" field MUST be an array.

If verdict is "REVISE", the issues array MUST contain at least
one issue.

Each issue MUST contain:

{
  "type": "string",
  "severity": "high" or "medium" or "low",
  "claim": "the problematic claim from the report",
  "reason": "why the claim is unsupported or incorrect"
}

Example:

{
  "verdict": "REVISE",
  "issues": [
    {
      "type": "unsupported_causal_claim",
      "severity": "high",
      "claim": "The latency was caused by /slow.",
      "reason": "The evidence establishes correlation but does not establish causation."
    }
  ],
  "summary": "The report contains an unsupported causal claim."
}

Do NOT use a "status" field.
Do NOT return {"status":"REVISE"}.
Do NOT use Markdown code fences.
Do NOT include any text before or after the JSON object.

Use "PASS" only when no material issues remain.
Use "REVISE" when one or more material issues are present.
"""


model = OpenAIModel(
    client_args={
        "api_key": os.environ["OPENAI_API_KEY"],
        "base_url": "https://bedrock-mantle.us-east-1.api.aws/v1",
    },
    model_id="zai.glm-4.7-flash",
)


CAUSAL_ASSERTION_PATTERNS = [
    "was caused by",
    "were caused by",
    "is caused by",
    "are caused by",
    "directly caused",
    "proximate cause is",
    "resulted from",
    "results from",
]


UNSUPPORTED_ABSENCE_CLAIMS = [
    "no deployment occurred",
    "no deployment happened",
    "no scaling occurred",
    "no scaling happened",
    "no configuration change occurred",
    "no configuration change happened",
    "no task replacement occurred",
    "no task replacement happened",
    "no deployment or scaling occurred",
]


UNSUPPORTED_STATISTICAL_PATTERNS = [
    "correlation coefficient",
    "statistically significant",
    "statistically insignificant",
    "p-value",
    "p value",
    "confidence interval",
]


def deterministic_statistical_review(
    report: str,
) -> list[dict]:
    """
    Detect unsupported statistical claims.

    Statistical terminology is only treated as a violation when the
    report presents it as calculated evidence without clearly stating
    that the calculation or test was not performed.
    """

    report_lower = report.lower()
    issues = []

    safe_context_markers = [
        "not calculated",
        "not performed",
        "not computed",
        "not available",
        "cannot be assessed",
        "cannot assess",
        "not established",
        "no statistical test",
        "without a statistical test",
        "insufficient evidence",
        "not measured",
        "not provided",
    ]

    for pattern in UNSUPPORTED_STATISTICAL_PATTERNS:
        if pattern not in report_lower:
            continue

        pattern_index = report_lower.find(pattern)

        start = max(
            0,
            pattern_index - 100,
        )

        end = min(
            len(report_lower),
            pattern_index + len(pattern) + 150,
        )

        context = report_lower[start:end]

        if any(
            marker in context
            for marker in safe_context_markers
        ):
            continue

        issues.append(
            {
                "type": "unsupported_statistical_claim",
                "severity": "medium",
                "claim": pattern,
                "reason": (
                    "The report uses statistical terminology without "
                    "evidence that the corresponding calculation or "
                    "statistical test was actually performed."
                ),
            }
        )

    return issues


def deterministic_review(report: str) -> list[dict]:
    """
    Enforce hard evidence-discipline rules without relying on an LLM.
    """

    report_lower = report.lower()
    issues = []

    for pattern in CAUSAL_ASSERTION_PATTERNS:
        if pattern in report_lower:
            issues.append(
                {
                    "type": "unsupported_causal_language",
                    "severity": "high",
                    "claim": pattern,
                    "reason": (
                        "The report contains assertive causal language, "
                        "but direct causal evidence has not been established."
                    ),
                }
            )

    for pattern in UNSUPPORTED_ABSENCE_CLAIMS:
        if pattern in report_lower:
            issues.append(
                {
                    "type": "unsupported_absence_claim",
                    "severity": "high",
                    "claim": pattern,
                    "reason": (
                        "Absence of queried CloudTrail events does not "
                        "prove that the underlying infrastructure change "
                        "did not occur."
                    ),
                }
            )

    issues.extend(
        deterministic_statistical_review(report)
    )

    return issues


def review_report(
    report: str,
    evidence: dict,
) -> dict:
    """
    Review a Sentinel report.

    Deterministic hard checks run first. Only reports that pass those
    checks are sent to the LLM reviewer for semantic review.
    """

    deterministic_issues = deterministic_review(report)

    if deterministic_issues:
        return {
            "verdict": "REVISE",
            "issues": deterministic_issues,
            "summary": (
                "Deterministic evidence-discipline checks found "
                "one or more hard violations."
            ),
        }

    prompt = f"""
Review the following Sentinel investigation report against the
supplied fixed evidence.

EVIDENCE:
{json.dumps(evidence, indent=2)}

REPORT:
{report}

Return only the required JSON review object.
"""

    reviewer = Agent(
        model=model,
        system_prompt=REVIEWER_SYSTEM_PROMPT,
    )

    response = reviewer(prompt)

    try:
        text = response.message["content"][0]["text"]
        cleaned_text = text.strip()

        if cleaned_text.startswith("```"):
            lines = cleaned_text.splitlines()

            if lines[0].strip().startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned_text = "\n".join(lines).strip()

        result = json.loads(cleaned_text)

        if "status" in result and "verdict" not in result:
            result["verdict"] = result.pop("status")

        if "issues" not in result:
            result["issues"] = []

        if "summary" not in result:
            result["summary"] = ""

        return result

    except (
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        raw_text = locals().get("text", "")

        return {
            "verdict": "REVISE",
            "issues": [
                {
                    "type": "invalid_reviewer_output",
                    "severity": "high",
                    "claim": raw_text[:500],
                    "reason": (
                        f"Reviewer did not return valid JSON: {exc}"
                    ),
                }
            ],
            "summary": "Reviewer output could not be parsed as JSON.",
        }