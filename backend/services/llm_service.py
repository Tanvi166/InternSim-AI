import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv
try:
    from groq import Groq
except ImportError:  # pragma: no cover
    class Groq:
        def __init__(self, api_key: str = None):
            self.api_key = api_key

        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    # Return a minimal structure mimicking Groq response
                    class Message:
                        def __init__(self):
                            self.content = "{}"
                    class Choice:
                        def __init__(self):
                            self.message = Message()
                    class Response:
                        def __init__(self):
                            self.choices = [Choice()]
                    return Response()

try:
    from google import genai
except ImportError:  # pragma: no cover
    class _StubGeminiClient:
        def __init__(self, api_key: str = None):
            self.api_key = api_key

        class models:
            @staticmethod
            async def generate_content(*args, **kwargs):
                # Return a minimal object with a .text attribute
                class Resp:
                    text = "{}"
                return Resp()

    class genai:
        class Client:
            def __init__(self, api_key: str = None):
                self._client = _StubGeminiClient(api_key)

            def __call__(self, *args, **kwargs):
                return self._client

            def __getattr__(self, name):
                return getattr(self._client, name)
from pydantic import BaseModel
from typing import Type, TypeVar, Any

# Explicitly load .env from backend directory
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

T = TypeVar('T', bound=BaseModel)

def get_groq_client():
    key = os.environ.get("GROQ_API_KEY")
    return Groq(api_key=key) if key else None

def get_gemini_client():
    key = os.environ.get("GEMINI_API_KEY")
    return genai.Client(api_key=key) if key else None

def parse_json_response(raw_text: str, response_schema: Type[T]) -> T:
    text = raw_text.strip()
    
    # Strip markdown code block wrappers if present
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if match:
            text = match.group(1).strip()
        else:
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text).strip()

    # Try parsing json directly
    try:
        data = json.loads(text, strict=False)
        return response_schema.model_validate(data)
    except Exception:
        pass

    # Extract first JSON object or array if surrounded by extra text
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        json_str = match.group(0)
        data = json.loads(json_str, strict=False)
        return response_schema.model_validate(data)

    return response_schema.model_validate_json(text)


def generate_ai_response(
    prompt: str,
    response_schema: Type[T],
    temperature: float = 0.2
) -> T:
    """
    Primary: Groq Qwen.
    Fallback: Groq GPT-OSS models, then Gemini.
    Always returns a validated Pydantic model instance.
    """

    system_prompt = (
        "You are an expert AI assistant. You must respond in JSON format ONLY.\n"
        "Do not include markdown formatting, preambles, or explanations outside JSON.\n"
        "Your output MUST be a single valid JSON object strictly matching this schema:\n"
        f"{json.dumps(response_schema.model_json_schema())}"
    )

    errors = []

    groq_client = get_groq_client()

    if groq_client:
        models_to_try = [
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ]

        for model in models_to_try:
            try:
                chat_completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )

                content = chat_completion.choices[0].message.content

                if not content:
                    raise ValueError("Model returned an empty response.")

                result = parse_json_response(content, response_schema)
                print(f"[AI SUCCESS] Groq model: {model}")
                return result

            except Exception as e:
                err_msg = f"Groq ({model}) API failed: {e}"
                print(f"{err_msg}. Trying next model...")
                errors.append(err_msg)

    gemini_client = get_gemini_client()

    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=[system_prompt + "\n\n" + prompt],
                config={
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                },
            )

            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            result = parse_json_response(response.text, response_schema)
            print("[AI SUCCESS] Gemini fallback")
            return result

        except Exception as e:
            err_msg = f"Gemini API failed: {e}"
            print(err_msg)
            errors.append(err_msg)

    if not errors:
        raise Exception(
            "No AI clients configured. Check GROQ_API_KEY / GEMINI_API_KEY "
            "in backend/.env"
        )

    raise Exception(
        f"All AI providers failed. Details: {'; '.join(errors)}"
    )

