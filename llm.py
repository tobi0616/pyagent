"""llm.py —— 与大模型 API 交互（仅标准库）

职责：
1. 封装 OpenAI 兼容的 Chat Completions 接口调用
2. 统一处理网络错误、API 错误与重试
3. 把响应解析成内部统一的 message 格式，屏蔽 API 差异
"""

import json
import os
import urllib.request
import urllib.error
import time


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

# TODO: 从环境变量读取，避免硬编码密钥
API_KEY  = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
MODEL    = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

# TODO: 调参入口，先用保守默认值
DEFAULT_TEMPERATURE = 0.3
REQUEST_TIMEOUT     = 60      # 单次请求超时（秒）
MAX_RETRIES         = 2       # 网络层失败的重试次数


# ---------------------------------------------------------------------------
# 异常定义
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """所有 LLM 相关错误的基类。"""


class LLMNetworkError(LLMError):
    """网络不可达、超时等传输层错误（可重试）。"""


class LLMAPIError(LLMError):
    """API 返回非 200，如鉴权失败、参数非法、限流（4xx 一般不可重试）。"""


# ---------------------------------------------------------------------------
# 核心接口
# ---------------------------------------------------------------------------

def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """发送一轮对话，返回解析后的 assistant message。

    Args:
        messages: OpenAI 格式的消息列表，[{"role": ..., "content": ...}, ...]
        tools:    tools.py 生成的 JSON schema 列表；None 表示纯文本对话

    Returns:
        统一格式的 assistant 消息，结构如下：
        {
            "role": "assistant",
            "content": str | None,        # 文本回复（调用工具时可能为 None）
            "tool_calls": [               # 无工具调用时为空列表
                {
                    "id": str,
                    "name": str,          # 工具名（已从 function.name 拍平）
                    "arguments": dict,    # 已 json.loads 的参数
                },
                ...
            ],
        }

    Raises:
        LLMNetworkError: 重试耗尽后仍失败
        LLMAPIError:     API 返回错误（含响应体中的报错信息）
    """
    payload = _build_payload(messages, tools)
    # TODO: 带重试地调用 _post()，捕获 LLMNetworkError，重试 MAX_RETRIES 次
    # TODO: 解析响应并返回 _parse_response(resp_json)

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp_json = _post(payload)
            return _parse_response(resp_json)
        except LLMNetworkError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(0.5)

# ---------------------------------------------------------------------------
# 内部函数
# ---------------------------------------------------------------------------

def _build_payload(messages: list[dict], tools: list[dict] | None) -> dict:
    """组装请求体。

    TODO:
      - 基础字段：model / messages / temperature
      - tools 非空时附加 tools 和 tool_choice="auto"
      - 注意：不要把内部拍平后的 tool_calls 格式直接回传，
        需要还原成 API 要求的嵌套结构（见 _encode_tool_calls）
    """
    encoded_messages = []
    for msg in messages:
        if msg.get("role") == "assistant":
            msg = dict(msg)
            if msg.get("tool_calls"):
                msg = {**msg, "tool_calls" : _encode_tool_calls(msg["tool_calls"])}
            else:
                msg.pop("tool_calls", None)
        encoded_messages.append(msg)
    # print(encoded_messages)
    payload = {
        "model": MODEL,
        "messages": encoded_messages,
        "temperature": DEFAULT_TEMPERATURE,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload
	


def _post(payload: dict) -> dict:
    """发起一次 HTTP POST，返回解析后的 JSON。

    
    TODO:
      - urllib.request.Request 构造请求：
            url     = f"{BASE_URL}/chat/completions"
            headers = Authorization: Bearer {API_KEY}, Content-Type: application/json
            data    = json.dumps(payload).encode("utf-8")
      - urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
      - 异常分类：
            urllib.error.HTTPError  → 读响应体，raise LLMAPIError（含状态码）
            urllib.error.URLError / TimeoutError → raise LLMNetworkError
      - 提示：HTTPError 也是 file-like 对象，e.read().decode() 能拿到
        API 返回的错误详情，对调试 tool_calls 格式问题非常关键
    """

    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)

    except urllib.error.HTTPError as e:
        # API 收到了请求，但返回了 4xx/5xx —— 通常是请求本身有问题
        detail = e.read().decode("utf-8", errors="replace")  # 关键！
        raise LLMAPIError(f"HTTP {e.code}: {detail}") from e

    except urllib.error.URLError as e:
        # 网络层失败：DNS 解析不了、连接被拒等，e.reason 里有原因
        raise LLMNetworkError(f"网络错误: {e.reason}") from e

    except TimeoutError as e:
        # 注意：超时抛的是内置 TimeoutError，不是 URLError
        raise LLMNetworkError("请求超时") from e


def _parse_response(resp_json: dict) -> dict:
    """把 API 原始响应解析成内部统一格式。

    TODO:
      - 取 resp_json["choices"][0]["message"]
      - content 原样保留（可能为 None）
      - tool_calls 拍平：
            API 返回: {"id": ..., "function": {"name": ..., "arguments": "<json 字符串>"}}
            内部格式: {"id": ..., "name": ..., "arguments": <dict>}
      - arguments 是 JSON 字符串，json.loads 失败时兜底为 {"_raw": 原字符串}，
        让 agent 层把解析错误反馈给模型，而不是直接崩
      - 顺手校验 resp_json 里是否有 "error" 字段（有些平台 200 也报错）
    """
    if "error" in resp_json:
        raise LLMAPIError(f"API 错误：{resp_json['error']}")
    message = resp_json["choices"][0]["message"]

    tool_calls = []
    for tc in message.get("tool_calls") or []:
        try:
            arguments = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            arguments = {"_parse_error": tc["function"]["arguments"]}
        tool_calls.append({
            "id": tc["id"],
            "name": tc["function"]["name"],
            "arguments": arguments
        })
    return {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": tool_calls,
    }

def _encode_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """把内部拍平格式还原为 API 要求的嵌套格式。

    什么时候用：agent 把 assistant 的 tool_calls 消息回放进历史时，
    API 只认 {"id", "type": "function", "function": {"name", "arguments": str}}，
    arguments 必须重新 json.dumps 成字符串。

    TODO: 实现转换，与 _parse_response 互为逆操作
    """
    encoded : list[dict] = []
    for tc in tool_calls:
        encoded.append({
            "id": tc["id"],
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments" : json.dumps(tc["arguments"], ensure_ascii = False)
            }
        })
    return encoded


if __name__ == "__main__":
    # 用例一：纯文本对话
    print("=" * 20, "用例一：纯文本", "=" * 20)
    resp = chat([{"role": "user", "content": "用一句话介绍 Python"}])
    assert resp["role"] == "assistant"
    assert resp["tool_calls"] == []
    assert resp["content"], "content 不应为空"
    print("通过:", resp["content"])

    # 用例二：触发工具调用
    print("=" * 20, "用例二：工具调用", "=" * 20)
    test_tools = [{"type": "function", "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {"type": "object",
                       "properties": {"city": {"type": "string"}},
                       "required": ["city"]},
    }}]
    resp = chat([{"role": "user", "content": "北京天气怎么样？"}], test_tools)
    assert resp["tool_calls"], "模型没发起工具调用，多跑一两次"
    tc = resp["tool_calls"][0]
    assert tc["name"] == "get_weather"
    assert isinstance(tc["arguments"], dict), "arguments 应是 dict 而非字符串"
    assert "city" in tc["arguments"]
    print("通过:", tc)

    # 用例三：tool_calls 回放 + tool 结果（模拟 ReAct 第二轮）
    print("=" * 20, "用例三：历史回放", "=" * 20)
    history = [
        {"role": "user", "content": "北京天气怎么样？"},
        resp,  # 用例二返回的 assistant 消息，原样放入历史
        {"role": "tool", "tool_call_id": tc["id"],
         "content": "北京：晴，25°C"},  # 伪造的工具执行结果
    ]
    resp3 = chat(history, test_tools)
    assert resp3["content"], "模型应基于 tool 结果给出文本回答"
    print("通过:", resp3["content"])