import os
import sys
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
env_path = os.path.join(BASE_DIR, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print('GEMINI_API_KEY not found in environment or backend/.env')
    sys.exit(2)

try:
    from google import genai
except Exception as e:
    print('Failed to import google.genai:', e)
    sys.exit(3)

client = genai.Client(api_key=GEMINI_API_KEY)
model = 'models/gemini-flash-latest'
print(f'Testing chat model: {model}')
try:
    chat = client.chats.create(model=model, history=[{"role":"model","parts":[{"text":"You are a friendly assistant."}]}])
    resp = chat.send_message('Hi')
    text = getattr(resp, 'text', None)
    if text:
        print('Response.text:\n', text)
    elif getattr(resp, 'candidates', None):
        print('Response candidate content:\n', resp.candidates[0].content)
    else:
        print('Full response object:\n', resp)
except Exception as e:
    print('Error calling chat.send_message:', repr(e))
    sys.exit(4)
