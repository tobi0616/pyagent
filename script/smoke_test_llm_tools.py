"""test_integration.py —— llm.py 与 tools.py 的联调测试"""
import terminal_tools           # 关键：import 即触发 @tool 装饰器，注册四个工具
from tools import get_schemas, dispatch
from llm import chat

# 1. 先确认注册表非空（防止"模型看不见工具"的静默失败）
schemas = get_schemas()
assert len(schemas) == 4, f"应有 4 个工具，实际 {len(schemas)} 个，检查 import 是否生效"
print(f"已注册工具: {[s['function']['name'] for s in schemas]}")

# 2. 让模型自主决定调用工具
resp = chat(
    [{"role": "user", "content": "看看当前目录下有哪些文件"}],
    schemas,
)
print("模型响应:", resp)

# 3. 验证模型发起了正确的工具调用
assert resp["tool_calls"], "模型没调工具，多跑一两次"
tc = resp["tool_calls"][0]
assert tc["name"] == "list_dir", f"期望 list_dir，实际 {tc['name']}"
print(f"通过：模型决定调用 {tc['name']}，参数 {tc['arguments']}")

# 4. 顺手把 dispatch 也串进来，手动模拟一轮 ReAct
result = dispatch(tc["name"], tc["arguments"])
print("工具执行结果:\n" + result)

# 5. 把结果喂回模型，验证它能给出最终回答（完整闭环）
history = [
    {"role": "user", "content": "看看当前目录下有哪些文件"},
    resp,
    {"role": "tool", "tool_call_id": tc["id"], "content": result},
]
final = chat(history, schemas)
print("最终回答:", final["content"])