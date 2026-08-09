
import openai
import os

# Configuration matching config.py
VLLM_CHAT_URL = "http://localhost:8000/v1"
VLLM_MODEL = "/app/llm/lora/Qwen3-32B-Instruct"
VLLM_API_KEY = "EMPTY"

client = openai.OpenAI(
    base_url=VLLM_CHAT_URL,
    api_key=VLLM_API_KEY,
)

print(f"Testing VLLM at {VLLM_CHAT_URL} with model {VLLM_MODEL}...")

try:
    response = client.chat.completions.create(
        model=VLLM_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, say something!"}
        ],
        max_tokens=50,
        temperature=0.7,
    )
    print("Response received:")
    print(response.choices[0].message.content)
except Exception as e:
    print(f"Error communicating with VLLM: {e}")
