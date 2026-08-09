from openai import OpenAI

# 初始化 OpenAI 客户端（配置为本地服务，兼容 OpenAI 格式）
client = OpenAI(
    # 1. 关键：指定本地服务的基础地址（替换 OpenAI 官方 API 地址）
    base_url="http://localhost:11434/v1",  # 本地 OpenAI 兼容服务通常路径为 /v1
    # 2. 关键：OpenAI 客户端要求必须提供 api_key，本地服务可随意填写非空值即可
    api_key="dummy_key_123456",  # 占位符，本地服务一般不校验该值（若有校验需填写对应值）
)

def openai_style_rag_query(stream=True):
    """
    OpenAI 风格调用本地大模型，查询 RAG 相关问题（支持流式返回）
    """
    try:
        # 调用 OpenAI 风格的 completions 接口（对应你原本的 generate 接口）
        response = client.chat.completions.create(
            model="demo2-rag",  # 你的模型名称，与原请求一致
            messages=[  # OpenAI 风格核心：使用 messages 传递对话，而非单独的 prompt
                {
                    "role": "user",
                    "content": "报关?"
                }
            ],
            stream=stream,  # 开启流式返回，与原请求一致
            temperature=0.7,  # 可选：调整生成随机性，按需配置
            max_tokens=2048 # 可选：限制生成内容长度，按需配置
        )

        # 处理流式返回（逐段获取内容并打印）
        if stream:
            full_response = ""
            for chunk in response:
                # 提取流式片段中的有效内容
                chunk_content = chunk.choices[0].delta.content or ""
                if chunk_content:
                    full_response += chunk_content
                    # 实时打印片段（模拟打字机效果）
                    print(chunk_content, end="", flush=True)
            return full_response

        # 处理非流式返回（直接获取完整结果）
        else:
            full_response = response.choices[0].message.content
            print("===== 非流式返回结果 =====")
            print(full_response)
            return full_response

    except Exception as e:
        print(f"调用接口失败：{str(e)}")
        return None

# 运行函数（默认开启流式返回，与你的原 curl 命令一致）
if __name__ == "__main__":
    openai_style_rag_query(stream=True)
