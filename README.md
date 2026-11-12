# pyagent

一个用 Python 实现的最小 ReAct Agent：通过 OpenAI 兼容的 Chat Completions API 与大模型交互，支持工具调用（Tool Calling），并在受限工作区内读写文件、执行 shell 命令。

整个项目**只依赖 Python 标准库**，没有第三方包。

## 特性

- **ReAct 循环**：模型思考 → 调用工具 → 结果回灌 → 继续推理，直到给出最终回答
- **工具调用**：用 `@tool` 装饰器注册普通函数，自动从签名和 docstring 生成 JSON Schema
- **四个内置工具**：列目录、读文件、写文件、执行 shell 命令
- **工作区沙箱**：文件操作被限制在指定目录内，阻止 `../` 和绝对路径逃逸
- **命令执行保护**：统一工作目录、超时终止、输出截断
- **容错设计**：工具异常不会中断 Agent 循环，错误信息会作为工具结果返回给模型
- **交互式 REPL**：支持 `/help`、`/history`、`/clear`、`/exit`

## 目录结构

```text
pyagent/
├── main.py                     # 程序入口：交互式 REPL
├── agent.py                    # ReAct 循环，维护对话历史
├── llm.py                      # Chat Completions API 封装、请求/响应解析、重试
├── tools.py                    # @tool 装饰器、Schema 生成、dispatch 分发
├── terminal_tools.py           # 四个内置工具的实现
├── sandbox.py                  # 工作区路径校验 + 命令执行
├── debug.py                    # DEBUG=1 时输出调试信息
├── script/
│   └── smoke_test_llm_tools.py # 联调脚本：真实调用 API 验证工具调用闭环
└── .gitignore
```

## 环境要求

- Python **3.10+**（用到 `list[dict]`、`X | None` 等语法）
- 一个支持 Tool Calling 的 **OpenAI 兼容** Chat Completions API
  （默认指向 DeepSeek，也可换成 OpenRouter、Kimi 等）
- 无需安装任何第三方依赖

## 快速开始

### 1. 配置环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `LLM_API_KEY` | 是 | 空 | API 密钥 |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com` | API 地址，末尾不要带 `/chat/completions` |
| `LLM_MODEL` | 否 | `deepseek-v4-flash` | 模型名，且必须支持工具调用 |
| `AGENT_WORKSPACE` | 否 | `.` | Agent 的工作区根目录，导入时解析为绝对路径 |
| `DEBUG` | 否 | 空 | 设为 `1` 时启用调试输出 |

```bash
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-v4-flash"
```

> 程序**不会自动读取 `.env`**。如果想用 `.env` 文件，请在启动前自行加载，例如：
>
> ```bash
> set -a; source .env; set +a
> ```
>
> `.env` 已被 `.gitignore` 忽略，不要把它提交到仓库。

### 2. 启动 REPL

```bash
python3 main.py
```

示例：

```text
Agent 已启动，输入 /help 查看命令。

 你 > 当前目录下有哪些 Python 文件？
Agent > 共有 7 个 Python 文件：agent.py、debug.py、...
```

REPL 命令：

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示帮助 |
| `/history` | 查看当前历史消息条数 |
| `/clear` | 清空历史（新建 Agent 实例） |
| `/exit` | 退出 |

`Ctrl+C` / `Ctrl+D` 也会优雅退出。

### 3. 单次运行（可选）

```bash
python3 agent.py
```

会执行文件末尾写死的一个测试任务，用于快速验证链路是否打通。

## 内置工具

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `list_dir` | `path="."` | 列出目录内容，目录名以路径分隔符结尾 |
| `read_file` | `path` | 读取文本文件全部内容（UTF-8） |
| `write_file` | `path`, `content` | 覆盖写入文件，父目录不存在时自动创建 |
| `run_command` | `command`, `timeout=30` | 在工作区内执行 shell 命令 |

工具的 JSON Schema 由 `tools.py` 在导入时自动生成，直接发送给模型。新增工具的步骤：

```python
from tools import tool

@tool
def my_tool(arg: str) -> str:
    """工具描述（模型看到的第一行文字）。

    :param arg: 参数说明
    """
    return "结果"
```

然后在 `agent.py` 中 import 所在模块，使装饰器执行、工具完成注册。

## 架构与数据流

```text
main.py  (REPL)
   │
   ▼
Agent.run(user_input)
   │
   ├─ llm.chat(messages, tools) ──HTTP──▶ Chat Completions API
   │        ▲                                  │
   │        └──── tools.get_schemas() ─────────┘
   │
   ├─ 有 tool_calls ?
   │     ├─ 是 → tools.dispatch(name, arguments)
   │     │         └─ terminal_tools.* → sandbox.safe_path() / sandbox.run()
   │     │         └─ 结果作为 tool 消息写回历史 → 继续循环
   │     └─ 否 → 返回 content，本轮结束
   │
   └─ 最多循环 MAX_ITERATIONS = 20 次
```

| 模块 | 职责 |
| --- | --- |
| `main.py` | REPL、斜杠命令、异常兜底 |
| `agent.py` | 对话历史、ReAct 循环、工具调用编排 |
| `llm.py` | HTTP 请求、错误分类与重试、消息格式转换 |
| `tools.py` | 工具注册表、Schema 生成、`dispatch` 容错分发 |
| `terminal_tools.py` | 工具的业务实现 |
| `sandbox.py` | 路径校验、统一 cwd 的命令执行 |

## 内部消息格式

`llm.chat()` 返回的消息使用**拍平后的** tool_calls 格式，方便 agent 层直接使用：

```python
{
    "role": "assistant",
    "content": str | None,
    "tool_calls": [
        {"id": "...", "name": "run_command", "arguments": {"command": "ls"}},
    ],
}
```

真正发请求前，`_build_payload()` 会把它还原成 API 要求的嵌套格式：

```json
{
  "id": "...",
  "type": "function",
  "function": {"name": "run_command", "arguments": "{\"command\": \"ls\"}"}
}
```

几个约定：

- 没有工具调用时，内部消息保留 `"tool_calls": []`，但**发送前会删除该字段**——部分 API（如 DeepSeek）不接受空的 `tool_calls` 数组。
- 模型给出的 `arguments` 若不是合法 JSON，会被包成 `{"_parse_error": ...}` 交给 `dispatch`，最终作为错误提示返回给模型，而不是直接崩溃。
- 每条 tool 消息的 `tool_call_id` 必须与对应 tool_call 的 `id` 一致。

## 沙箱与安全边界

- `sandbox.safe_path()` 使用 `os.path.realpath()` 归一化路径（解析 `..` 和符号链接），再校验是否位于工作区内。
- `sandbox.run()` 以 `WORKSPACE` 为 cwd 执行命令，默认 30 秒超时，stdout/stderr 各保留前 5000 字符。
- `AGENT_WORKSPACE` 在模块导入时解析，运行中修改环境变量不会生效。

> ⚠️ 这是"防误操作"的工作区围栏，**不是安全容器**。模型生成的命令仍以当前用户权限执行，不要用它运行不可信代码。

## 测试脚本

`script/smoke_test_llm_tools.py` 会真实调用 API，验证完整的工具调用闭环（注册 → 模型决策 → dispatch → 结果回灌）。运行会产生费用：

```bash
PYTHONPATH=. python3 script/smoke_test_llm_tools.py
```

脚本依赖模型稳定地选择 `list_dir`，偶尔需要多跑一两次。

## 已知限制

- 对话历史只增不减，没有压缩或截断（长会话会持续消耗上下文）。
- 达到 `MAX_ITERATIONS` 后 `Agent.run()` 会返回 `None`，调用方需要额外兜底。
- 无流式输出；工具调用与回答都是一次性返回。
- `llm._post()` 的 `TimeoutError` 分支引用了未定义的变量 `e`，真发生超时时会抛 `NameError`。
- REPL 对 `LLMError` 只打印固定提示，调试时需要直接运行 `agent.py` 或加日志。
