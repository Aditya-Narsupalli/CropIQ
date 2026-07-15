import json
import urllib.request

url = 'http://127.0.0.1:8000/api/v1/chat/message'
payload = {
    "message": "What should I do about yellowing leaves?",
    "language": "en",
    "context_data": {"location": "Baramati, Maharashtra, India"},
    "agent": "crop_doctor"
}

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(resp.status)
        print(resp.read().decode('utf-8'))
except Exception as e:
    try:
        import urllib.error
        if isinstance(e, urllib.error.HTTPError):
            body = e.read().decode('utf-8', errors='replace')
            print('HTTP Error:', e.code)
            print('Body:', body)
        else:
            print('Request failed:', e)
    except Exception:
        print('Request failed:', e)
