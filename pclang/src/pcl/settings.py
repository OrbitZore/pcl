"""settings — 设置文件（用户级/项目级）的发现、解析、合并与校验（docs/SETTINGS.md）。

- **只服务 CLI 层**：库形态（run_program/compile_program/importer）不读设置，
  调用方显式传参（DESIGN §6/A12 隔离不变式）；
- 发现：用户级 ``$PCL_CONFIG_FILE``（重定向；缺失即报错）或缺省
  ``$XDG_CONFIG_HOME/pcl/settings.json``（缺失跳过）；项目级自入口 ``.pcl``
  向上取**最近一个** ``.pcl/settings.json``（``PCL_NO_PROJECT_CONFIG`` 或
  显式 ``no_project`` 跳过）；
- 格式：**JSONC 子集**——预剥离字符串字面量之外的 ``//``/``/* */`` 注释与
  尾随逗号后交 ``json.loads``（tsconfig/VS Code 先例；剥离保留换行数，
  JSON 错误行号不失真）；
- 合并：内置默认 ← 用户级 ← 项目级；节内浅合并；``pi.args`` 拼接
  （用户 → 项目；CLI ``--pi-arg`` 由 cli 再追加）；
- 信任模型（§3.5）：``pi.*`` / ``script.path`` 仅用户级——项目级出现即
  ``SettingsError``（克隆仓库不可静默指定执行面）；项目级 ``cache.dir``
  须为相对路径且解析结果落在设置文件目录之内；
- 相对路径以**设置文件所在目录**为基准展开（``pi.bin`` 仅在含路径分隔符时
  展开，裸名交 PATH；``pi.connector_path == "none"`` 为哨兵不展开）；
- 校验：未知键 stderr 警告（用户级 ``"strict": true`` 升级为报错）；类型/
  取值错误、坏 JSON、违反信任模型 → ``SettingsError``（CLI 呈现为 exit 1）；
  ``$`` 前缀键（``$schema``/``$comment``）忽略不告警。
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Settings", "SettingsError", "BUILTIN", "resolve_settings",
           "strip_jsonc", "user_settings_path", "project_settings_path"]


class SettingsError(Exception):
    """设置文件错误（CLI 呈现为 exit 1，与编译期同码）。"""

    def __init__(self, message: str, *, file=None, line=None, col=None):
        self.message = message
        self.file = file
        self.line = line
        self.col = col
        super().__init__(message)

    def format(self) -> str:
        prefix = ""
        if self.file is not None:
            prefix = f"{self.file}:{self.line or 1}:{self.col or 1} "
        return f"{prefix}{self.message}"


# ---- 内置默认（§4；与 settings.schema.json 保持同步） -------------------------

BUILTIN: dict = {
    "agent": "pi",
    "timeout": 300.0,
    "trace": False,
    "strict": False,
    "cache": {"dir": None, "disable": False, "keep_per_stem": 2},
    "pi": {"bin": "pi", "connector_path": "none", "args": []},
    "script": {"path": None},
}

_AGENTS = {"pi", "null", "script", "embed"}

# 仅用户级（执行面/外部资源，§3.5 信任模型）——扁平点分键
_USER_ONLY = ("pi.bin", "pi.connector_path", "pi.args", "script.path")

_TOP_KEYS = {"agent", "timeout", "trace", "strict", "cache", "pi", "script"}
_SECTION_KEYS = {
    "cache": {"dir", "disable", "keep_per_stem"},
    "pi": {"bin", "connector_path", "args"},
    "script": {"path"},
}


def _warn(msg: str):
    try:
        sys.stderr.write(f"pcl: 警告：{msg}\n")
    except Exception:
        pass


def _env_flag(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in {"1", "true", "yes", "on"}


# ---- JSONC 子集（stdlib 剥离） -----------------------------------------------

def strip_jsonc(text: str) -> str:
    """剥离字符串字面量之外的 ``//``、``/* */`` 注释与尾随逗号。

    换行数保持不变（块注释以等量换行替换），JSON 语法错误的行号不失真。
    """
    text = _strip_comments(text)
    return _strip_trailing_commas(text)


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j        # 保留行尾换行
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            end = n if j == -1 else j + 2
            out.append("\n" * text.count("\n", i, end))   # 保行号
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1                     # 丢弃尾随逗号
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SettingsError(f"无法读取设置文件：{e}", file=path) from None
    except UnicodeDecodeError as e:
        raise SettingsError(f"设置文件不是合法 UTF-8：{e}", file=path) from None
    try:
        data = json.loads(strip_jsonc(raw))
    except json.JSONDecodeError as e:
        raise SettingsError(f"设置文件语法错误：{e.msg}", file=path,
                            line=e.lineno, col=e.colno) from None
    if not isinstance(data, dict):
        raise SettingsError("设置文件顶层须为 JSON 对象", file=path, line=1, col=1)
    return data


# ---- 发现 ---------------------------------------------------------------------

def user_settings_path(env: Mapping[str, str] | None = None) -> tuple[Path, bool]:
    """用户级设置路径 → (路径, 是否显式重定向)。"""
    env = env if env is not None else os.environ
    redirected = env.get("PCL_CONFIG_FILE")
    if redirected:
        return Path(redirected), True
    base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"),
                                                      ".config")
    return Path(base) / "pcl" / "settings.json", False


def project_settings_path(entry: Path | str | None, env: Mapping[str, str] | None = None,
                          *, no_project: bool = False) -> Path | None:
    """项目级设置：自入口 .pcl 所在目录向上取最近的 .pcl/settings.json。"""
    env = env if env is not None else os.environ
    if no_project or _env_flag(env.get("PCL_NO_PROJECT_CONFIG")):
        return None
    if entry is None:
        return None
    d = Path(entry).resolve().parent
    for candidate in (d, *d.parents):
        p = candidate / ".pcl" / "settings.json"
        if p.is_file():
            return p
    return None


# ---- 合并与校验 -----------------------------------------------------------------

@dataclass
class Settings:
    """解析后的有效设置（路径均已按来源文件基准展开为绝对路径）。"""

    agent: str = "pi"
    timeout: float = 300.0
    trace: bool = False
    strict: bool = False
    cache_dir: str | None = None
    cache_disable: bool = False
    cache_keep_per_stem: int = 2
    pi_bin: str = "pi"
    pi_connector_path: str = "none"
    pi_args: list[str] = field(default_factory=list)
    script_path: str | None = None
    origins: dict[str, str] = field(default_factory=dict)   # 扁平键 → 来源标签
    sources: list[str] = field(default_factory=list)        # 实际读入的文件

    def flat(self) -> dict:
        return {
            "agent": self.agent,
            "timeout": self.timeout,
            "trace": self.trace,
            "strict": self.strict,
            "cache.dir": self.cache_dir,
            "cache.disable": self.cache_disable,
            "cache.keep_per_stem": self.cache_keep_per_stem,
            "pi.bin": self.pi_bin,
            "pi.connector_path": self.pi_connector_path,
            "pi.args": self.pi_args,
            "script.path": self.script_path,
        }


def _type_err(path, key, want, got):
    return SettingsError(f"设置项 {key} 类型错误：应为 {want}，得到 {got}",
                         file=path)


def _check_layer(data: dict, path: Path, layer: str, *, strict: bool) -> dict:
    """校验单层文件：未知键（警告/严格报错）+ 类型/取值检查。返回规范化后的
    扁平键值（dotted → 已按该文件基准展开路径的值）。"""
    flat: dict = {}

    def fail(msg, line=1, col=1):
        raise SettingsError(msg, file=path, line=line, col=col)

    for key, val in data.items():
        if isinstance(key, str) and key.startswith("$"):
            continue    # $schema / $comment：忽略不告警
        if key not in _TOP_KEYS:
            msg = f"{path}: 未知设置键 {key!r}（将忽略）"
            if strict:
                fail(f"未知设置键 {key!r}（strict 模式）")
            _warn(msg)
            continue
        if key in ("agent", "timeout", "trace", "strict"):
            if key == "agent":
                if not isinstance(val, str) or val not in _AGENTS:
                    fail(f"设置项 agent 须为 {'/'.join(sorted(_AGENTS))}，得到 {val!r}")
                flat["agent"] = val
            elif key == "timeout":
                if isinstance(val, bool) or not isinstance(val, (int, float)) \
                        or val <= 0:
                    fail(f"设置项 timeout 须为正数（秒），得到 {val!r}")
                flat["timeout"] = float(val)
            else:
                if not isinstance(val, bool):
                    raise _type_err(path, key, "bool", type(val).__name__)
                flat[key] = val
            continue
        # 节键
        if not isinstance(val, dict):
            raise _type_err(path, key, "对象", type(val).__name__)
        for sk, sv in val.items():
            if isinstance(sk, str) and sk.startswith("$"):
                continue
            if sk not in _SECTION_KEYS[key]:
                msg = f"{path}: 未知设置键 {key}.{sk!r}（将忽略）"
                if strict:
                    fail(f"未知设置键 {key}.{sk!r}（strict 模式）")
                _warn(msg)
                continue
            dotted = f"{key}.{sk}"
            if dotted == "cache.dir":
                if sv is not None and not isinstance(sv, str):
                    raise _type_err(path, dotted, "路径字符串或 null",
                                    type(sv).__name__)
            elif dotted == "cache.disable":
                if not isinstance(sv, bool):
                    raise _type_err(path, dotted, "bool", type(sv).__name__)
            elif dotted == "cache.keep_per_stem":
                if isinstance(sv, bool) or not isinstance(sv, int) or sv <= 0:
                    fail(f"设置项 cache.keep_per_stem 须为正整数，得到 {sv!r}")
            elif dotted in ("pi.bin", "pi.connector_path"):
                if not isinstance(sv, str) or not sv:
                    raise _type_err(path, dotted, "非空字符串", repr(sv))
            elif dotted == "pi.args":
                if not isinstance(sv, list) or any(not isinstance(a, str) for a in sv):
                    raise _type_err(path, dotted, "字符串数组", repr(sv))
            elif dotted == "script.path":
                if sv is not None and not isinstance(sv, str):
                    raise _type_err(path, dotted, "路径字符串或 null",
                                    type(sv).__name__)
            flat[dotted] = sv

    # 路径展开（以该文件所在目录为基准，§2）
    base = path.parent
    if "cache.dir" in flat and flat["cache.dir"] is not None:
        flat["cache.dir"] = _resolve_path(flat["cache.dir"], base)
    if "pi.connector_path" in flat and flat["pi.connector_path"] != "none":
        flat["pi.connector_path"] = _resolve_path(flat["pi.connector_path"], base)
    if "script.path" in flat and flat["script.path"] is not None:
        flat["script.path"] = _resolve_path(flat["script.path"], base)
    if "pi.bin" in flat and os.sep in flat["pi.bin"]:
        # 仅含路径分隔符时按文件基准展开；裸名（如 "pi"）交 PATH 解析
        flat["pi.bin"] = _resolve_path(flat["pi.bin"], base)
    return flat


def _resolve_path(value: str, base: Path) -> str:
    p = Path(value)
    if not p.is_absolute():
        p = base / p
    return str(p)


def _check_trust(flat: dict, path: Path, layer: str):
    """§3.5 信任模型：项目级不得含执行面键；cache.dir 不得逃逸。"""
    if layer != "project":
        return
    for dotted in _USER_ONLY:
        if dotted in flat:
            raise SettingsError(
                f"项目级设置不得包含执行面键 {dotted!r}"
                f"（仅用户级可用；请移至用户级设置）", file=path)
    cd = flat.get("cache.dir")
    if cd is not None:
        raw = _raw_cache_dir(path)
        if raw is not None and (Path(raw).is_absolute() or ".." in Path(raw).parts):
            raise SettingsError(
                "项目级 cache.dir 须为相对路径", file=path)
        base = path.parent.resolve()
        target = Path(cd).resolve()
        if not target.is_relative_to(base):
            raise SettingsError(
                f"项目级 cache.dir 逃逸出项目目录：{cd}", file=path)


def _raw_cache_dir(path: Path):
    """重读文件取原始 cache.dir（未展开）——用于相对性判定。"""
    try:
        data = _load_jsonc(path)
    except SettingsError:
        return None
    cd = data.get("cache")
    if isinstance(cd, dict):
        v = cd.get("dir")
        if isinstance(v, str):
            return v
    return None


def resolve_settings(entry: Path | str | None = None, *,
                     no_project: bool = False,
                     env: Mapping[str, str] | None = None) -> Settings:
    """发现 + 解析 + 合并（内置 ← 用户 ← 项目）。库形态不应调用本函数。"""
    env = env if env is not None else os.environ

    user_path, redirected = user_settings_path(env)
    user_flat: dict = {}
    strict = False
    sources: list[str] = []
    user_label = None

    if user_path.is_file():
        data = _load_jsonc(user_path)
        # strict 只看用户级（§7：用户级开关）
        strict = bool(data.get("strict")) if isinstance(data.get("strict"), bool) \
            else False
        user_flat = _check_layer(data, user_path, "user", strict=strict)
        sources.append(str(user_path))
        user_label = f"user:{user_path}"
    elif redirected:
        raise SettingsError(f"PCL_CONFIG_FILE 指向的设置文件不存在：{user_path}",
                            file=user_path)

    proj_path = project_settings_path(entry, env, no_project=no_project)
    proj_flat: dict = {}
    proj_label = None
    if proj_path is not None and proj_path.is_file():
        data = _load_jsonc(proj_path)
        proj_flat = _check_layer(data, proj_path, "project", strict=strict)
        _check_trust(proj_flat, proj_path, "project")
        sources.append(str(proj_path))
        proj_label = f"project:{proj_path}"

    # 合并（扁平键；pi.args 拼接特例）
    merged: dict = {}
    origins: dict[str, str] = {}
    for flat, label in ((user_flat, user_label), (proj_flat, proj_label)):
        if label is None:
            continue
        for k, v in flat.items():
            if k == "pi.args":
                merged.setdefault("pi.args", [])
                merged["pi.args"] = list(merged["pi.args"]) + list(v)
                origins[k] = (origins.get(k, "builtin") + f" + {label}"
                              if origins.get(k) not in (None, "builtin")
                              else label)
            else:
                merged[k] = v
                origins[k] = label

    st = Settings(
        agent=merged.get("agent", BUILTIN["agent"]),
        timeout=merged.get("timeout", BUILTIN["timeout"]),
        trace=merged.get("trace", BUILTIN["trace"]),
        strict=strict or merged.get("strict", False),
        cache_dir=merged.get("cache.dir", BUILTIN["cache"]["dir"]),
        cache_disable=merged.get("cache.disable", BUILTIN["cache"]["disable"]),
        cache_keep_per_stem=merged.get("cache.keep_per_stem",
                                       BUILTIN["cache"]["keep_per_stem"]),
        pi_bin=merged.get("pi.bin", BUILTIN["pi"]["bin"]),
        pi_connector_path=merged.get("pi.connector_path",
                                     BUILTIN["pi"]["connector_path"]),
        pi_args=merged.get("pi.args", []),
        script_path=merged.get("script.path", BUILTIN["script"]["path"]),
        origins=origins,
        sources=sources,
    )
    return st
