"""main.py —— 程序入口，REPL 交互

职责：
1. 创建 Agent 实例（一个进程 = 一段持续会话）
2. 循环读取用户输入，交给 agent.run()，打印回答
3. 提供斜杠命令：/exit、/clear、/history、/help
4. 兜底异常，保证 REPL 永不崩溃退出
"""

from agent import Agent
from llm import LLMError


HELP = """可用命令：
  /exit     退出
  /clear    清空对话历史（开始新会话）
  /history  查看当前历史消息数
  /help     显示本帮助
其他输入会直接交给 Agent 处理。"""


def main():
    agent = Agent()
    print("Agent 已启动，输入 /help 查看命令。")

    while True:
        # TODO: 读取输入
        #   try: user_input = input("\n你 > ").strip()
        #   except (EOFError, KeyboardInterrupt):
        #       处理 Ctrl+D / Ctrl+C：打印提示并 break，优雅退出

        try: 
            user_input = input("\n 你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            return

        # TODO: 空输入跳过
        #   if not user_input: continue
        if not user_input: 
            continue

        # TODO: 斜杠命令分支
        #   /exit    → break
        #   /clear   → agent = Agent()（直接换新实例，历史自然清空）
        #   /history → print(f"当前历史共 {len(agent.messages)} 条消息")
        #   /help    → print(HELP)
        #   其他以 / 开头的 → 提示未知命令
        if user_input == "/exit":
            print("\n退出")
            return
        if user_input == "/clear":
            agent = Agent()
            continue
        if user_input == "/history":
            print(f"\n当前历史共 {len(agent.messages)} 条消息")
            continue
        if user_input == "/help":
            print("\n", HELP)
            continue

        # TODO: 正常输入交给 Agent
        #   try:
        #       answer = agent.run(user_input)
        #       print(f"\nAgent > {answer}")
        #   except LLMError as e:
        #       打印错误（如 API 失败），但不退出 REPL，用户可以继续
        #   except Exception as e:
        #       兜底：打印"内部错误"，同样不退出
        try:
            answer = agent.run(user_input)
            print(f"\nAgent > {answer}")
        except LLMError as e:
            print("\nAPI 失败")
        except Exception as e:
            print("\n内部错误")

if __name__ == "__main__":
    main()