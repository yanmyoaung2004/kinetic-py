"""Cloudflare Workers AI test — simple + tool call via OpenAI SDK.

Usage:
    py openai_test.py "What is the capital of France?"
    py openai_test.py "What's the weather in Tokyo?" --tool

Set env vars:
    CLOUD_FLARE_API_KEY=cfat_...
    CLOUD_FLARE_USER_ID=<account-id>
"""

import json
import os
import sys

import dotenv
from openai import OpenAI

dotenv.load_dotenv()

client = OpenAI(
    api_key=os.environ.get("CLOUD_FLARE_API_KEY") or "",
    base_url=f"https://api.cloudflare.com/client/v4/accounts/{os.environ.get('CLOUD_FLARE_USER_ID', '')}/ai/v1",
)

MODEL = os.environ.get("CLOUD_FLARE_MODEL", "@cf/meta/llama-3.2-3b-instruct")


def simple_call(prompt: str) -> str:
    r = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""


def tool_call(prompt: str) -> str:
    """Tool call — Cloudflare supports tool definitions but not injecting tool results."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["location"],
                },
            },
        }
    ]
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        tools=tools,
        tool_choice="auto",
    )
    msg = r.choices[0].message

    if msg.tool_calls:
        tc = msg.tool_calls[0]
        lines = [f"Model called: {tc.function.name}"]
        args = json.loads(tc.function.arguments)
        lines.append(f"Arguments: {json.dumps(args, indent=2)}")
        lines.append("")
        lines.append("Note: Cloudflare Workers AI doesn't support tool result injection.")
        lines.append("The second step (tool result -> final response) requires a different endpoint.")
        return "\n".join(lines)

    return f"Text: {msg.content}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py openai_test.py <prompt> [--tool]")
        sys.exit(1)

    prompt = sys.argv[1]
    use_tools = "--tool" in sys.argv

    print(f"Model: {MODEL}")
    print(f"Prompt: {prompt}")
    print("-" * 40)

    result = tool_call(prompt) if use_tools else simple_call(prompt)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(result)


# Test both:
# .venv\Scripts\python.exe openai_test.py "What is the capital of France?"
# .venv\Scripts\python.exe openai_test.py "What's the weather in Tokyo?" --tool