"""sandbox.py —— 工具执行的沙箱环境

职责：
1. 工作区隔离：所有文件操作限制在 WORKSPACE 目录内，阻止 ../ 逃逸
2. 命令执行控制：统一 cwd、超时、输出截断

定位说明：
    这是"防误操作"的工作区围栏，不是安全容器。
    模型生成的命令仍有完整用户权限，不要用它运行不可信代码。

使用方式：
    terminal_tool.py 的四个工具不再直接操作文件系统，
    而是调用本模块的 safe_path() 和 run()。
"""

import os
import subprocess


# ---------------------------------------------------------------------------
# 配置：工作区根目录
# ---------------------------------------------------------------------------

# TODO: 默认用当前目录，支持环境变量覆盖，方便测试时指向临时目录
WORKSPACE = os.path.realpath(os.environ.get("AGENT_WORKSPACE", "."))


# ---------------------------------------------------------------------------
# 核心一：路径校验
# ---------------------------------------------------------------------------

def safe_path(path: str) -> str:
    """把用户/模型给的路径解析为绝对路径，并校验它在工作区内。

    Args:
        path: 相对路径（相对工作区）或绝对路径

    Returns:
        校验通过的绝对路径，供 open()/os.listdir() 等使用

    Raises:
        ValueError: 路径逃逸出工作区（错误信息会被 dispatch 喂回模型，
                    所以要写得让模型看得懂，比如"路径超出工作区范围"）

    TODO:
      1. 相对路径先拼到工作区上：
         full = os.path.realpath(os.path.join(WORKSPACE, path))
         —— realpath 会解析 ../ 和符号链接，这是防逃逸的关键
      2. 校验前缀：
         if full != WORKSPACE and not full.startswith(WORKSPACE + os.sep):
             raise ValueError(...)
         —— 注意要 + os.sep！否则 /workspace_evil 会被误判为在 /workspace 内
      3. 返回 full
    """
    full = os.path.realpath(os.path.join(WORKSPACE, path))
    if full != WORKSPACE and not full.startswith(WORKSPACE + os.sep):
        raise ValueError("路径超出工作区范围")
    return full

# ---------------------------------------------------------------------------
# 核心二：命令执行
# ---------------------------------------------------------------------------

def run(command: str, timeout: int = 30) -> str:
    """在工作区内执行 shell 命令，返回格式化结果。

    TODO（把 terminal_tool.run_command 的逻辑搬过来，加两点强化）:
      1. subprocess.run(..., cwd=WORKSPACE)  ← 统一在工作区执行
      2. 输出截断：stdout/stderr 各保留前 5000 字符，
         截断时追加 "\n...（已截断）"
      3. 返回格式保持：f"返回码: {...}\nstdout:\n...\nstderr:\n..."
      4. TimeoutExpired 捕获后返回友好提示
    """
    try:
        result = subprocess.run(
            command, shell = True,
            capture_output = True, text = True,
            timeout = timeout,
            cwd = WORKSPACE
        )
    except subprocess.TimeoutExpired:
        return f"命令执行超过 {timeout} 秒被终止"
    else:
        stdout = result.stdout if len(result.stdout) <= 5000 else result.stdout[:5000] + "\n...（已截断）"
        stderr = result.stderr if len(result.stderr) <= 5000 else result.stderr[:5000] + "\n...（已截断）"
        return f"返回码：{result.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"

# ---------------------------------------------------------------------------
# 冒烟测试
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 正常路径：应解析到工作区内
    print(safe_path("llm.py"))
    print(safe_path("subdir/../llm.py"))     # realpath 归一化后仍在工作区

    # 逃逸路径：应抛 ValueError
    for evil in ["../outside.txt", "/etc/passwd", "a/../../b.txt"]:
        try:
            safe_path(evil)
            print(f"[失败] {evil} 没被拦截")
        except ValueError as e:
            print(f"[通过] 拦截 {evil}: {e}")

    # 命令执行
    print(run("pwd && echo '---' && ls -la"))
    print(run("sleep 100", timeout=2))       # 应报超时