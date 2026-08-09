import requests
import json
import os

# Login to get token
base_url = "http://localhost:8081"
# We need a valid user. Let's use the one from previous tests or register a new one.
# Assuming admin/admin works or we can register.
username = "test_dup_user"
password = "password123"

# Register/Login
auth_url = f"{base_url}/register"
try:
    requests.post(auth_url, json={"username": username, "password": password, "email": "test@example.com", "role": "user"})
except:
    pass

login_url = f"{base_url}/login"
resp = requests.post(login_url, json={"username": username, "password": password})
if resp.status_code != 200:
    print(f"Login failed: {resp.text}")
    # Try registering again with random user
    import random
    username = f"test_{random.randint(1000,9999)}"
    requests.post(auth_url, json={"username": username, "password": password, "email": "test@example.com", "role": "user"})
    resp = requests.post(login_url, json={"username": username, "password": password})

token = resp.json().get("access_token")

print(f"Token: {token[:10]}...")

# Stream request
stream_url = f"{base_url}/api/chat/stream"
headers = {"Authorization": f"Bearer {token}"}
data = {"question": "如何做外贸", "user_id": username}

print("Starting stream...")
with requests.post(stream_url, json=data, headers=headers, stream=True) as r:
    for line in r.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if "token" in decoded_line:
                 print(f"TOKEN: {decoded_line}")
            else:
                 print(f"OTHER: {decoded_line}")
