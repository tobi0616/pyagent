"""tools.py —— 工具管理模块（仅标准库）

职责：
1. 提供 @tool 装饰器：把普通 Python 函数注册为 Agent 可用工具
2. 从函数签名 + 类型注解 + docstring 自动生成 JSON Schema
3. 提供两个出口：
   - get_schemas() → 给 llm.chat()，每轮请求全量发送
   - dispatch()    → 给 agent.py，按名字调用工具并容错

模块加载顺序约定：
    agent.py 里 import terminal_tool，触发装饰器执行，注册表才有内容。
"""

import inspect
import json


# ---------------------------------------------------------------------------
# 类型映射：Python 类型注解 → JSON Schema 类型
# MVP 只支持基础类型，遇到不支持的类型直接报错并指明是哪个参数
# ---------------------------------------------------------------------------

TYPE_MAP = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


# ---------------------------------------------------------------------------
# 注册表：模块级单例
# 结构：{"list_dir": {"func": <函数对象>, "schema": {...}}, ...}
# 写入时机：import terminal_tool 时，装饰器逐个执行
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 装饰器
# ---------------------------------------------------------------------------

def tool(func):
    """注册一个工具函数，原样返回函数本身（不改变其行为）。

    用法：
        @tool
        def list_dir(path: str = ".") -> str:
            '''列出目录内容。

            :param path: 目录路径
            '''
            ...
    """
    schema = _build_schema(func)
    _REGISTRY[func.__name__] = {"func": func, "schema": schema}
    return func


# ---------------------------------------------------------------------------
# schema 生成（本模块的核心难点）
# ---------------------------------------------------------------------------

def _build_schema(func) -> dict:
    """从函数对象生成 API 要求的嵌套 schema。

    返回结构（这就是"标准答案"的形状）：
        {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": <docstring 第一行>,
                "parameters": {
                    "type": "object",
                    "properties": {
                        <参数名>: {"type": <JSON类型>, "description": <参数描述>},
                        ...
                    },
                    "required": [<没有默认值的参数名>, ...],
                },
            },
        }

    TODO:
      1. doc = inspect.getdoc(func) or ""
         description, param_docs = _parse_docstring(doc)
      2. sig = inspect.signature(func)
         遍历 sig.parameters.items()，对每个参数：
           - annotation = param.annotation
             若是 inspect.Parameter.empty（没写注解）→ 默认按 str 处理
             否则查 TYPE_MAP，查不到 → raise ValueError，
             报错信息里带上 函数名 + 参数名 + 类型（装饰器在 import 时执行，
             没有清晰报错会很难排查）
           - param.default is inspect.Parameter.empty → 加入 required
             （注意：不能用 if not param.default 判断，False/0/"" 都是合法默认值）
      3. 组装嵌套 dict 返回
    """
    description, param_docs = _parse_docstring(inspect.getdoc(func) or "")

    properties = {}
    required = []

    sig = inspect.signature(func)
    for name, param in sig.parameters.items():
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            json_type = "string"
        elif annotation in TYPE_MAP:
            json_type = TYPE_MAP[annotation]
        else:
            raise ValueError(
                f"工具 {func.__name__} 的参数 {name} "
                f"使用了不支持的类型 {annotation}"
            )

        properties[name] = {
            "type": json_type,
            "description": param_docs.get(name, ""),
        }

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function":{
            "name": func.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }

def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """解析 docstring，返回 (工具描述, {参数名: 参数描述})。

    约定格式（写在工具函数的 docstring 里）：
        列出目录内容。          ← 第一行：工具描述

        :param path: 目录路径   ← :param 名: 描述 形式的行：参数描述
        :param show_hidden: 是否显示隐藏文件

    TODO:
      1. 按行 split，strip 每行
      2. 第一行非空行 → 工具描述
      3. 以 ":param " 开头的行 → 切分出参数名和描述
         提示：line.removeprefix(":param ").split(":", 1)
      4. 其余行忽略（MVP 不处理多行描述）
    """
    description = ""
    param_docs = {}

    for line in doc.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(":param "):
            body = line.removeprefix(":param ")
            name, _, desc = body.partition(":")
            param_docs[name.strip()] = desc.strip()
        elif not description:
            description = line
    return description, param_docs
        

# ---------------------------------------------------------------------------
# 出口一：给 llm.py 的 schema 列表
# ---------------------------------------------------------------------------

def get_schemas() -> list[dict]:
    """返回所有已注册工具的 schema。

    注意：注册表在 import terminal_tool 后才非空。
    如果这里返回空列表，先检查是不是忘了 import。
    """
    return [entry["schema"] for entry in _REGISTRY.values()]


# ---------------------------------------------------------------------------
# 出口二：给 agent.py 的调用分发
# 铁律：任何错误都返回字符串，绝不把异常抛给 agent 循环
# ---------------------------------------------------------------------------

def dispatch(name: str, arguments: dict) -> str:
    """按名字调用工具，结果统一转成字符串。

    Args:
        name:      模型给出的工具名
        arguments: _parse_response 解析后的 dict（可能含 _parse_error）

    Returns:
        工具执行结果的字符串，或一段"写给模型看的"错误提示。

    TODO（按顺序处理四种情况）:
      1. "_parse_error" in arguments
         → 返回 "工具参数不是合法 JSON，请重新生成调用。原始内容：..."
      2. name not in _REGISTRY
         → 返回 "工具 {name} 不存在，可用工具：{列出所有名字}"
      3. try: result = _REGISTRY[name]["func"](**arguments)
           返回 str(result)，可选：超长截断（比如 5000 字符）
      4. except Exception as e:
           → 返回 "工具执行出错: {type(e).__name__}: {e}"
           （TypeError 通常意味着模型把参数名写错了，
             错误原文能帮助它自我纠正，不要省略）
    """
    if "_parse_error" in arguments:
        return (
            "工具参数不是合法 JSON，请重新生成完整调用。"
            f"你上次输出的原始内容：{arguments['_parse_error']}"
        )

    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY)
        return f"工具 {name} 不存在。可用工具：{available}"

    try:
        result = _REGISTRY[name]["func"](**arguments)
        text = str(result)
        if len(text) > 5000:
            text = text[:5000]+ "\n...（输出过长，已截断）"
        return text
    except Exception as e:
        return f"工具执行出错：{type(e).__name__} : {e}"
# ---------------------------------------------------------------------------
# 冒烟测试：先写一个测试工具，验证 schema 生成和 dispatch
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 第一步：定义一个覆盖"必填参数 + 可选参数 + bool 类型"的测试函数
    @tool
    def list_dir(path: str = ".", show_hidden: bool = False) -> str:
        """列出指定目录下的文件。

        :param path: 目录路径
        :param show_hidden: 是否显示隐藏文件
        """
        return f"模拟返回: path={path}, show_hidden={show_hidden}"

    # 第二步：打印生成的 schema，肉眼对照标准答案
    # 期望 properties 里 path 是 string、show_hidden 是 boolean，
    # 两者都有 description，required 是空列表
    @tool
    def read_file(path: str) -> str:
        """读取文件内容。

        :param path: 文件路径
        """
        return "..."

    print(json.dumps(get_schemas(), ensure_ascii=False, indent=2))

    # 第三步：验证 dispatch 的四条路径
    print(dispatch("list_dir", {"path": "/tmp"}))         # 正常调用
    print(dispatch("list_dir", {}))                       # 全部用默认值
    print(dispatch("nonexist", {}))                       # 工具不存在 → 字符串
    print(dispatch("list_dir", {"_parse_error": "{bad"})) # 解析失败 → 字符串
    print(dispatch("list_dir", {"wrong_arg": 1}))         # 参数名错 → 字符串
    # 五条都必须有输出，任何一条抛异常都算不达标