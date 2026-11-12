"""agent.py —— ReAct 模式的 Agent 循环

职责：
1. 维护对话历史（当前版本直接用 list，memory.py 完成后再接入压缩）
2. 驱动 ReAct 循环：模型响应 → 有 tool_calls 就执行并喂回 → 直到模型给出文本回答
3. 对 main.py 暴露唯一入口 run(user_input) -> str

数据流回顾：
    user 输入 → 追加 user 消息 → chat() → assistant 消息入历史
    → 若有 tool_calls：逐个 dispatch，结果以 tool 消息入历史 → 再 chat()
    → 若无 tool_calls：content 就是最终回答，返回
"""

import terminal_tools                      # 关键：import 即注册工具，不能删
from llm import chat, LLMError
from tools import get_schemas, dispatch
import json
from debug import debug

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 20    # 防止模型陷入无限工具调用的保险丝

SYSTEM_PROMPT = """你是一个能通过工具完成任务的编程 Agent。

工作方式：
1. 分析用户的任务，规划需要哪些步骤
2. 通过调用工具来执行：查看目录、读写文件、运行命令
3. 根据工具返回的结果决定下一步，直到任务完成
4. 任务完成后，用简洁的中文总结你做了什么、结果如何

注意：
- 所有文件操作都在工作区内进行，使用相对路径
- 工具返回错误时，分析原因并换种方式重试，不要重复相同的错误调用
- 修改代码前先读文件了解现状，修改后运行命令验证
"""


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

class Agent:
    """一个 Agent 实例 = 一段持续的会话（历史在实例间不共享）。"""

    def __init__(self):
        # TODO: 初始化历史，system 消息永远在第一条
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.tools = get_schemas()

    def run(self, user_input: str) -> str:
        """处理一轮用户输入，返回 Agent 的最终文本回答。

        TODO:
          1. self.messages.append({"role": "user", "content": user_input})
          2. for _ in range(MAX_ITERATIONS):
               resp = chat(self.messages, self.tools)
               self.messages.append(resp)          # 原样入历史

               if not resp["tool_calls"]:
                   return resp["content"] or ""     # 无工具调用 = 最终回答

               self._execute_tool_calls(resp["tool_calls"])
          3. 循环耗尽：返回兜底提示，如 "达到最大步数，任务未完成"
        """
        self.messages.append({"role": "user", "content": user_input})
        for _ in range(MAX_ITERATIONS):
            # print("=" * 30, "发送前的 messages", "=" * 30)
            # print(json.dumps(self.messages, ensure_ascii=False, indent=2, default=str))
            
            resp = chat(self.messages, self.tools)
            self.messages.append(resp)
            if not resp["tool_calls"]:
                return resp["content"] or ""
            self._execute_tool_calls(resp["tool_calls"])
        return "达到最大步数，任务未完成"

    def _execute_tool_calls(self, tool_calls: list[dict]) -> None:
        """执行本轮所有工具调用，结果逐个追加为 tool 消息。

        TODO:
          for tc in tool_calls:
              result = dispatch(tc["name"], tc["arguments"])
              self.messages.append({
                  "role": "tool",
                  "tool_call_id": tc["id"],     # 必须与 tool_call 的 id 对应
                  "content": result,
              })

        注意：
          - 一个 assistant 消息可能带多个 tool_call，每个都要有一条对应的
            tool 消息，一条都不能少，否则下一轮请求 400
          - dispatch 保证不抛异常，这里不需要 try
        """
        for tc in tool_calls:
            result = dispatch(tc["name"], tc["arguments"])
            self.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result
            })

# ---------------------------------------------------------------------------
# 冒烟测试：真实任务端到端
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent = Agent()
    answer = agent.run("当前目录下有哪些 Python 文件？")
    print("Agent 回答:", answer)

    # 多轮：验证历史连续性
    answer = agent.run("把刚才列出的文件数量写进 stats.txt")
    print("Agent 回答:", answer)

    # answer = agent.run("测试一下 run_command 工具的可用性")
    # print("Agent 回答：", answer)