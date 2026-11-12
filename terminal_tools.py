"""terminal_tool.py —— Agent 可用的终端工具

每个函数 = 一个工具。约定：
1. 必须加 @tool 装饰器
2. 参数只用 str/int/bool 等基础类型，写全类型注解
3. docstring 按规范写：第一行工具描述，:param 行写参数描述
   —— 这些文字是给模型看的说明书，直接影响它填参数的准确率
4. 返回值统一为 str（dispatch 会兜底 str()，但主动返回 str 更可控）
5. 函数内部不 catch 异常 —— 出错让 dispatch 捕获并喂回模型
"""

import os
import subprocess

from tools import tool
from sandbox import safe_path, run


@tool
def list_dir(path: str = ".") -> str:
    """列出指定目录下的文件和子目录，目录以 / 结尾标记。

    :param path: 目录路径，默认为当前工作目录
    """
    # TODO:
    #   entries = sorted(os.listdir(path))
    #   遍历 entries，用 os.path.isdir(os.path.join(path, e)) 判断是否目录，
    #   目录名后加 "/"，方便模型区分文件和目录
    #   空目录返回 "(空目录)"，否则 "\n".join(结果)
    path = safe_path(path)
    entries = sorted(os.listdir(path))
    lines = []
    if not entries:
        return "(空目录)"
    for name in entries:
        if os.path.isdir(os.path.join(path, name)):
            lines.append(name + os.sep)
    for name in entries:
        if not os.path.isdir(os.path.join(path, name)):
            lines.append(name)
    return "\n".join(lines)

@tool
def read_file(path: str) -> str:
    """读取文本文件的全部内容。

    :param path: 文件路径
    """
    # TODO:
    #   with open(path, "r", encoding="utf-8") as f: return f.read()
    #   不用自己处理文件不存在 —— FileNotFoundError 交给 dispatch
    path = safe_path(path)
    with open(path, "r", encoding = "utf-8") as f:
        return f.read()

@tool
def write_file(path: str, content: str) -> str:
    """把内容写入文件，覆盖已有内容；父目录不存在时自动创建。

    :param path: 文件路径
    :param content: 要写入的完整内容
    """
    # TODO:
    #   parent = os.path.dirname(path)
    #   if parent: os.makedirs(parent, exist_ok=True)
    #   with open(path, "w", encoding="utf-8") as f: f.write(content)
    #   返回确认信息，如 f"已写入 {path}，共 {len(content)} 字符"
    #   —— 返回确认信息而不是 None，模型才知道操作成功了
    path = safe_path(path)
    parent = os.path.dirname(path)
    if parent: os.makedirs(parent, exist_ok = True)
    with open(path, "w", encoding = "utf-8") as f:
        f.write(content)
        return f"已写入 {path}，共 {len(content)} 字符"

@tool
def run_command(command: str, timeout: int = 30) -> str:
    """执行一条 shell 命令，返回标准输出和标准错误。

    :param command: 要执行的命令，如 python main.py 或 ls -la
    :param timeout: 超时秒数，超时后命令被强制终止
    """
    # TODO:
    #   result = subprocess.run(
    #       command, shell=True,
    #       capture_output=True, text=True,   # text=True 直接拿到 str
    #       timeout=timeout,
    #   )
    #   把 stdout 和 stderr 拼起来返回，非零返回码要体现在结果里：
    #   如 f"返回码: {result.returncode}\n{result.stdout}\n{result.stderr}"
    #
    #   subprocess.TimeoutExpired 不用自己 catch，dispatch 会处理；
    #   但注意它的报错信息对模型不直观，也可以自己 catch 后返回
    #   f"命令执行超过 {timeout} 秒被终止"
    return run(command, timeout)


if __name__ == "__main__":
    print(list_dir("."))
