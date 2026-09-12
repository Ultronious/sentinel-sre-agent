import os

from strands import Agent
from strands.models.openai import OpenAIModel

from tools import get_alarm_state,get_metrics


SYSTEM_PROMPT = """
You are Sentinel, an SRE investigation agent.

Your job is to investigate operational incidents.

Rules:
- Do not invent observations.
- Use available tools to gather evidence.
- Clearly distinguish observed facts from hypotheses.
- Do not perform remediation yet.
- If evidence is insufficient, say so.
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
    tools=[get_alarm_state, get_metrics],
)


if __name__ == "__main__":
    response = agent(
        """
Investigate the current Sentinel incident.

Investigation procedure:
1. Check the current high-latency alarm state.
2. Retrieve recent TargetResponseTime metrics.
3. Compare the observed metric values with the alarm threshold.
4. Clearly distinguish observed facts from hypotheses.
5. Do not invent a root cause.
6. If the available evidence is insufficient to determine the cause, say so.
7. Do not perform remediation.

Report:
- Alarm state
- Relevant metric observations
- What those observations establish
- What they do NOT establish
- Recommended next investigation step
"""

    )

    print(response)