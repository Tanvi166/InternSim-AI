
import os
import httpx
from pathlib import Path
from dotenv import load_dotenv

# Load the backend .env file
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("GROQ_API_KEY missing in backend/.env")
    raise SystemExit(1)

try:
    response = httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15
    )

    print("Status:", response.status_code)

    if response.status_code == 200:
        models = response.json().get("data", [])
        for model in models:
            print(model.get("id"))
    else:
        print(response.text[:500])

except Exception as e:
    print("Error:", e)
