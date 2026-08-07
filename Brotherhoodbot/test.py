import requests, base64, re

token = "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"
url = "https://api.github.com/repos/BrotherHood-Lab/BrotherHood/contents/BrotherHood.html"
headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

r = requests.get(url, headers=headers)
content = base64.b64decode(r.json()["content"]).decode("utf-8")

idx = content.find("today-inner")
print("=== Фрагмент вокруг today-inner ===")
print(repr(content[idx:idx+400]))
