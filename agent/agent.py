import os

from strands import Agent
from strands.models.openai import OpenAIModel

from tools import (
    get_alarm_history,
    get_alarm_state,
    get_ecs_lifecycle_events,
    get_metrics,
    query_logs,
    inspect_ecs_task,
    get_ecs_metrics,
    get_ecs_task_at_time,
    )


SYSTEM_PROMPT = """
You are Sentinel, an AWS SRE investigation agent.

ROLE
Investigate AWS operational incidents using available observability and
infrastructure tools. Perform read-only investigation autonomously.
Never invent evidence.

INVESTIGATION
1. Identify the relevant incident from alarm state and alarm history.
2. Anchor the investigation to the selected incident timestamp.
3. Gather relevant evidence from metrics, logs, application telemetry,
   resource state, and lifecycle/change history.
4. For historical incidents, call get_ecs_task_at_time() before
   get_ecs_metrics(). Never substitute a current task for a historical task.
5. Correlate evidence across independent sources.
6. Form hypotheses only after gathering evidence.
7. Attempt to validate the strongest hypothesis using independent evidence.
8. If validation is impossible, explicitly report the uncertainty.

INCIDENT SELECTION
When get_alarm_history() returns a non-null selected_incident:
- Treat selected_incident.timestamp as the ONLY incident timestamp.
- Do not replace it with another historical incident because it appears
  more severe or has a larger metric value.
- Do not independently choose another incident from alarm history.
- Pass the selected timestamp to subsequent investigation tools.

If selected_incident is null:
- Report that no ALARM incident was identified.
- Do not invent an incident timestamp.

HISTORICAL TASKS
For a historical incident:
- Call get_ecs_task_at_time() with the selected incident timestamp.
- If a candidate task ID is returned, pass that task ID to get_ecs_metrics().
- Never substitute the currently running task.
- If attribution is unavailable, state that task-level utilization could
  not be reliably attributed to the incident.
- Report observed values and timestamps.

EVIDENCE DISCIPLINE
- Observed = directly returned by a tool.
- Correlated = observations occurring in the same relevant time window.
- Hypothesis = plausible explanation supported by evidence.
- Validated root cause = causal mechanism directly established by evidence.

Rules:
- Temporal correlation alone is never causation.
- Never invent observations, metrics, logs, deployments, or causes.
- Never infer endpoint behavior or resource consumption from a name, path,
  HTTP method, or status code.
- Increased CPU does not by itself establish saturation or resource pressure.
- Never infer queueing, throttling, exhaustion, deployment causality,
  attack intent, or user impact without supporting evidence.
- Missing or conflicting evidence must be explicitly reported.
- Do not upgrade a hypothesis to a root cause merely because it is plausible.
- If causality is not established, state ROOT CAUSE: UNCONFIRMED.

APPLICATION TELEMETRY
When structured request telemetry is available:
- inspect request counts;
- inspect status codes;
- inspect latency statistics;
- inspect affected paths;
- compare application telemetry with infrastructure telemetry
  from the same incident window.

If application telemetry conflicts with another evidence source,
report the discrepancy rather than choosing one without justification.

FINAL CLAIM RULE
When causality is unproven, use:
"correlated with"
"strongest hypothesis"
"strongest correlated factor"

Do not use:
"caused by"
"cause"
"proximate cause"
"resulted from"
"because of"
"triggered by"

unless the available evidence directly establishes the causal mechanism.

Do not describe missing CloudTrail events as proof that no deployment,
scaling, task replacement, or configuration change occurred.

Do not describe a change as statistically significant or insignificant
unless a statistical test was actually performed.

When report synthesis begins, state that the available evidence has been
gathered. Do not claim that all required evidence exists when material
evidence gaps remain.

Produce exactly one final report. Do not repeat or regenerate it.

INVESTIGATION BEHAVIOR
- Continue read-only investigation without asking the user for permission.
- A recovered alarm does not end a historical investigation.
- Prefer incident-window evidence over unrelated current-state evidence.
- Do not recommend or execute remediation unless the evidence justifies it.
- Mutating or destructive actions require explicit human approval.

FINAL REPORT
Return exactly one concise report with these sections:

1. Incident
2. Observed evidence
3. Correlations
4. Strongest hypothesis
5. Missing or contradicting evidence
6. Validation status
7. Final conclusion

Clearly distinguish established facts, correlations, hypotheses,
and validated conclusions.

If the causal mechanism remains unproven, state:
ROOT CAUSE: UNCONFIRMED

State what additional evidence would be required for validation.
"""


model = OpenAIModel(
    client_args={
        "api_key": os.environ["OPENAI_API_KEY"],
        "base_url": "https://bedrock-mantle.us-east-1.api.aws/v1",
    },
    model_id="zai.glm-5",
)


agent = Agent(
    model=model,
    system_prompt=SYSTEM_PROMPT,
    tools=[
        get_alarm_state,
        get_alarm_history,
        get_metrics,
        query_logs,
        inspect_ecs_task,get_ecs_lifecycle_events,
        get_ecs_metrics,
        get_ecs_task_at_time,
    ],
)


if __name__ == "__main__":
    response = agent(
        """
Investigate the current Sentinel incident.

Use get_alarm_history() first.

When get_alarm_history() returns a non-null selected_incident:
- Treat selected_incident.timestamp as the ONLY incident timestamp
  for this investigation.
- Do not replace it with another historical incident because another
  incident has a larger latency value or appears more severe.
- Do not independently select a different incident from the returned
  history.
- Pass the selected incident timestamp to subsequent investigation tools.

If selected_incident is null:
- Report that no ALARM incident was identified.
- Do not invent an incident timestamp.

For historical ECS investigation:
- Call get_ecs_task_at_time() using the selected incident timestamp.
- If it returns a candidate task ID, pass that task ID to get_ecs_metrics().
- If it returns insufficient_evidence, do not substitute the current
  running task.



Do not perform remediation.

After completing the tool investigation, produce exactly ONE final report.
Do not repeat, restate, or regenerate the report.
Do not include an analysis section before or after the report.
Your response must end after the final conclusion.
Report:

1. Alarm state
2. Incident timestamp and investigation window
3. Relevant alarm history
4. Observed metric evidence
5. Observed application/log evidence
6. Observed ECS/resource evidence
7. Observed lifecycle/change evidence
8. Correlations across independent evidence sources
9. Strongest hypothesis
   - supporting observations
   - correlated observations
   - contradicting/missing evidence
   - unproven causal link
   - evidence required for validation
10. Final conclusion

The final conclusion must explicitly distinguish:
- what is established;
- what is correlated;
- what remains hypothetical;
- what remains unknown.

Never call something the root cause unless the evidence establishes
the causal mechanism.
"""

    )

    #print(response.message["content"][0]["text"])
    