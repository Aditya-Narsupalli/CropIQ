import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
env_path = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print('GEMINI_API_KEY not found in backend/.env or environment')
    raise SystemExit(2)

try:
    from google import genai
except Exception as e:
    print('Failed to import google.genai:', e)
    raise

client = genai.Client(api_key=GEMINI_API_KEY)
print('Listing models visible to this API key:')
try:
    models = list(client.models.list())
    names = [m.name for m in models]
    names.sort()
    for n in names:
        print(n)
    if not names:
        print('No models returned')
except Exception as e:
    print('Error listing models:', repr(e))
    raise
