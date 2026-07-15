import json
import urllib.request

url = 'http://127.0.0.1:8000/api/v1/multilingual_chat/message'
data = json.dumps({"message":"Hi","language":"en"}).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(resp.status)
        print(resp.read().decode('utf-8'))
except Exception as e:
    # If it's an HTTPError, try to print the response body for debugging
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
