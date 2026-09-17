"""PCL 错误类型与退出码（RFC 0000 §11 / RFC 0001 §10）。

- 编译期 L/P/C → 退出码 1
- 运行期 R → 退出码 2
- 桥接 A → 退出码 3
- SIGINT（R409）→ 退出码 130
"""

from __future__ import annotations

_EXIT_BY_CLASS = {"L": 1, "P": 1, "C": 1, "R": 2, "A": 3}


def exit_code_for(code: str) -> int:
    """按错误码前缀返回退出码。"""
    return _EXIT_BY_CLASS.get(code[:1], 1)


class PclError(Exception):
    """运行期（R）与桥接（A）错误。

    code 形如 "R400"；file/line/col 为错误归因到的 `.pcl` 位置（可能为空）。
    """

    def __init__(self, code: str, message: str, *, file: str | None = None,
                 line: int | None = None, col: int | None = None):
        self.code = code
        self.message = message
        self.file = file
        self.line = line
        self.col = col
        super().__init__(f"[{code}] {message}")

    def format(self) -> str:
        """`file.pcl:行:列 [CODE] 消息`（缺位置时省略前缀）。"""
        prefix = ""
        if self.file is not None:
            prefix = f"{self.file}:{self.line or 1}:{self.col or 1} "
        return f"{prefix}[{self.code}] {self.message}"


class PclCompileError(Exception):
    """编译期（L/P/C）错误，携带 `.pcl` 源位置。"""

    def __init__(self, code: str, message: str, *, file: str, line: int, col: int):
        self.code = code
        self.message = message
        self.file = file
        self.line = line
        self.col = col
        super().__init__(self.format())

    def format(self) -> str:
        return f"{self.file}:{self.line}:{self.col} [{self.code}] {self.message}"
