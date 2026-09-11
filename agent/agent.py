import os

from strands import Agent
from strands.models.openai import OpenAIModel

from tools import get_alarm_state


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
    tools=[get_alarm_state],
)


if __name__ == "__main__":
    response = agent(
        """
        Investigate the current Sentinel incident.

        First determine whether the high-latency alarm is currently firing.
        Report what you actually observe.
        Do not assume the cause.
        """
    )

    print(response)