import os
from openai import OpenAI

client = OpenAI(
    # Point the SDK to the custom provider instead of OpenAI's default servers
    base_url="https://opencode.ai/zen/go/v1",
    api_key=os.environ.get("OPENCODE_API_KEY"),
)

completion = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "user", "content": "Explain quantum computing in one sentence."}
    ]
)

print(completion.choices[0].message.content)