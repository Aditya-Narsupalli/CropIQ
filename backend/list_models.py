"""
Quick utility: lists the Gemini models available to your API key right now,
filtered to ones that support generateContent (i.e. usable for vision/text analysis).

Run from backend/ with your venv active:
    python list_models.py
"""
import os
from google import genai

api_key = os.getenv("GEMINI_API_KEY") or input("Paste your GEMINI_API_KEY: ").strip()

client = genai.Client(api_key=api_key)

print("\nModels available to this key that support generateContent:\n")
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
    if not actions or any("generateContent" in a for a in actions):
        print(f"  {m.name}")
