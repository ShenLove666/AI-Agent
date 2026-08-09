import time
import uuid
import json
import base64
import requests
import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ===== 配置 =====
SERVER_URL = "http://127.0.0.1:8081/chat"
PRIVATE_KEY_PATH = "auth/client_private.pem"

def load_private_key():
    """加载客户端私钥"""
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sign_request(method, path, body_bytes, private_key):
    """生成请求签名头"""
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())

    # 构造待签名串：METHOD \n PATH \n BODY_SHA256 \n TIMESTAMP \n NONCE
    body_hash = sha256_hex(body_bytes)
    canonical = f"{method.upper()}\n{path}\n{body_hash}\n{timestamp}\n{nonce}".encode("utf-8")

    # RSA 签名
    signature = private_key.sign(
        canonical,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    return {
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": sig_b64
    }

def main():
    print(f"🔹 正在加载私钥: {PRIVATE_KEY_PATH}...")
    try:
        private_key = load_private_key()
    except FileNotFoundError:
        print(f"❌ 错误: 找不到 {PRIVATE_KEY_PATH}。请在项目根目录运行。")
        return

    question = "什么情况下会触发查验？"
    payload = {"question": question, "user_id": "secure_user_01"}
    body_json = json.dumps(payload)
    body_bytes = body_json.encode("utf-8")

    # 生成签名头
    print("🔹 正在签名请求...")
    headers = sign_request("POST", "/chat", body_bytes, private_key)
    headers["Content-Type"] = "application/json"

    print(f"🚀 发送请求至 {SERVER_URL}...")
    try:
        resp = requests.post(SERVER_URL, data=body_bytes, headers=headers, timeout=120)

        if resp.status_code == 200:
            print("✅ 成功!")
            data = resp.json()
            print("Answer:", data.get("answer"))
            if "debug" in data:
                print("Debug Info:", json.dumps(data.get("debug"), ensure_ascii=False))
        elif resp.status_code == 401:
            print("❌ 认证失败 (401):", resp.text)
        else:
            print(f"⚠️ 错误 ({resp.status_code}):", resp.text)

    except Exception as e:
        print(f"❌ 连接错误: {e}")

if __name__ == "__main__":
    main()
