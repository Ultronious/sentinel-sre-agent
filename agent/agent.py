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
Investigate AWS operational incidents using the available observability
and infrastructure tools. Perform read-only investigation autonomously.
Never invent evidence.

INVESTIGATION
1. Identify the relevant incident from alarm state and alarm history.
2. Anchor the investigation to the selected incident timestamp.
3. Gather relevant evidence from metrics, logs, application telemetry,
   resource state, and lifecycle/change history.
4. For historical incidents, use get_ecs_task_at_time() before
   get_ecs_metrics(). Do not manually substitute a task based on current
   ECS state.
5. Correlate evidence across independent sources.
6. Form hypotheses only after gathering evidence.
7. Attempt to validate the strongest hypothesis using independent evidence.
8. If validation is impossible, explicitly report the uncertainty.

INCIDENT SELECTION
When get_alarm_history() returns a non-null selected_incident:
- Treat selected_incident.timestamp as the ONLY incident timestamp
  for this investigation.
- Do not replace it with another historical incident because another
  incident has a larger latency value or appears more severe.
- Do not independently select a different incident from alarm history.
- Pass the selected incident timestamp to subsequent investigation tools.

If selected_incident is null:
- Report that no ALARM incident was identified.
- Do not invent an incident timestamp.

HISTORICAL TASKS
When investigating a historical incident:
- Call get_ecs_task_at_time() using the selected incident timestamp.
- If it returns a candidate task ID, pass that task ID to get_ecs_metrics().
- Do not substitute the currently running task.
- If task attribution is unavailable, report that task-level utilization
  could not be reliably attributed to the incident.
- Report actual observed values and timestamps.

EVIDENCE DISCIPLINE
- Observed = directly returned by a tool.
- Correlated = observations occurring in the same relevant time window.
- Hypothesis = plausible explanation supported by evidence.
- Validated root cause = causal mechanism directly established by evidence.

Rules:
- Temporal correlation alone is never causation.
- Never invent observations, metrics, logs, deployments, or causes.
- Never infer endpoint behavior or resource consumption from its name,
  path, HTTP method, or status code.
- Increased CPU is not automatically CPU saturation.
- Never infer queueing, throttling, resource exhaustion, deployment
  causality, attack intent, or user impact without supporting evidence.
- Missing or conflicting evidence must be explicitly reported.
- Do not upgrade a hypothesis to a root cause merely because it is
  plausible or the strongest explanation.
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
Never use causal language such as:
"caused by", "cause", "proximate cause", "resulted from",
or "because of"
unless the available evidence directly establishes the causal mechanism.

When evidence shows temporal or quantitative alignment but causality
is unproven, use:
"correlated with"
"strongest hypothesis"
"strongest correlated factor"

Do not describe missing CloudTrail events as proof that no deployment,
scaling, task replacement, or configuration change occurred.

Do not describe a change as "statistically significant" or
"statistically insignificant" unless a statistical test was actually
performed.

When report synthesis begins, state that the available evidence has
been gathered. Do not claim that all required evidence exists when
material evidence gaps remain.

Produce the final investigation report exactly once.

INVESTIGATION BEHAVIOR
- Continue read-only investigation without asking the user for permission.
- A recovered alarm does not end a historical investigation.
- Prefer incident-window evidence over unrelated current-state evidence.
- Do not recommend or execute remediation unless the evidence justifies it.
- Mutating or destructive actions always require explicit human approval.

FINAL REPORT
Return a concise investigation report containing:

1. Incident
2. Observed evidence
3. Correlations
4. Strongest hypothesis
5. Missing or contradicting evidence
6. Validation status
7. Final conclusion

Clearly distinguish established facts, correlations, hypotheses,
and validated conclusions.

If the causal mechanism remains unproven, say:
ROOT CAUSE: UNCONFIRMED
and explain what evidence is still required for validation.
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

    print(response)