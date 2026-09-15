"""settings 单元测试：JSONC、发现、合并、信任模型、相对路径、strict（SETTINGS.md）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcl.settings import (
    BUILTIN,
    SettingsError,
    project_settings_path,
    resolve_settings,
    strip_jsonc,
    user_settings_path,
)

# ---- JSONC 子集 ---------------------------------------------------------------

def test_jsonc_comments_and_trailing_commas():
    src = """{
  // 行注释
  "agent": "null", /* 块
注释保换行 */
  "cache": {
    "disable": true,   // 尾随逗号
  },
}"""
    assert json.loads(strip_jsonc(src)) == {
        "agent": "null", "cache": {"disable": True}}


def test_jsonc_strings_untouched():
    src = '{"u": "https://x//y", "c": "/* not comment */", "s": "a,]"}'
    assert json.loads(strip_jsonc(src)) == json.loads(src)


def test_jsonc_line_numbers_preserved():
    # 块注释以等量换行替换：坏 JSON 的行号不失真
    src = '{\n/* a\nb\nc */\n"agent": oops\n}'
    out = strip_jsonc(src)
    with pytest.raises(json.JSONDecodeError) as ei:
        json.loads(out)
    assert ei.value.lineno == 5   # 注释占 3 行（2–4），键在原第 5 行


# ---- 发现 ---------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离：XDG 指向 tmp；清掉重定向与项目级开关。"""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("PCL_CONFIG_FILE", raising=False)
    monkeypatch.delenv("PCL_NO_PROJECT_CONFIG", raising=False)
    return tmp_path


def write_user(env, text: str) -> Path:
    p = Path(env) / "xdg" / "pcl" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_project(root: Path, text: str) -> Path:
    p = root / ".pcl" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_user_settings_path_xdg_and_redirect(env, monkeypatch):
    p, redirected = user_settings_path()
    assert not redirected and str(p).endswith("pcl/settings.json")
    monkeypatch.setenv("PCL_CONFIG_FILE", "/tmp/my.json")
    p, redirected = user_settings_path()
    assert redirected and str(p) == "/tmp/my.json"


def test_project_nearest_wins(env, tmp_path):
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    entry = deep / "t.pcl"
    write_project(tmp_path / "a", '{"trace": true}')
    write_project(deep, '{"trace": false}')
    assert project_settings_path(entry) == deep / ".pcl" / "settings.json"
    # 不合并多层：只取最近
    st = resolve_settings(entry)
    assert st.trace is False
    assert st.origins["trace"].startswith("project:")


def test_no_project_flag_and_env(env, tmp_path, monkeypatch):
    entry = tmp_path / "t.pcl"
    write_project(tmp_path, '{"trace": true}')
    assert project_settings_path(entry, no_project=True) is None
    monkeypatch.setenv("PCL_NO_PROJECT_CONFIG", "1")
    assert project_settings_path(entry) is None
    monkeypatch.setenv("PCL_NO_PROJECT_CONFIG", "0")
    assert project_settings_path(entry) is not None


def test_redirect_missing_file_errors(env, monkeypatch):
    monkeypatch.setenv("PCL_CONFIG_FILE", str(env / "nope.json"))
    with pytest.raises(SettingsError, match="PCL_CONFIG_FILE"):
        resolve_settings(None)


def test_default_user_missing_skips(env):
    st = resolve_settings(None)
    assert st.agent == BUILTIN["agent"] and not st.sources


# ---- 合并与优先级 ---------------------------------------------------------------

def test_precedence_and_section_shallow_merge(env, tmp_path):
    write_user(env, '{"agent": "null", "timeout": 10, "cache": {"dir": "udir"}}')
    root = tmp_path / "proj"
    root.mkdir()
    write_project(root, '{"timeout": 20, "cache": {"disable": true}}')
    st = resolve_settings(root / "t.pcl")
    assert st.agent == "null"            # 用户级独有 → 保留
    assert st.timeout == 20.0            # 项目级覆盖用户级
    assert st.cache_disable is True      # 项目级节内键
    assert st.cache_dir is not None and st.cache_dir.endswith("udir")  # 浅合并保留
    assert st.origins["agent"].startswith("user:")
    assert st.origins["timeout"].startswith("project:")
    assert st.origins["cache.disable"].startswith("project:")


def test_pi_args_concat_user_then_project(env, tmp_path):
    write_user(env, '{"pi": {"args": ["--u"]}}')
    write_project(tmp_path, '{"pi": {"args": ["--p"]}}')
    with pytest.raises(SettingsError, match="执行面键"):
        resolve_settings(tmp_path / "t.pcl")   # 项目级 pi.* 被信任模型拦截
    # 仅用户级时正常
    write_project(tmp_path, "{}")
    st = resolve_settings(tmp_path / "t.pcl")
    assert st.pi_args == ["--u"]


# ---- 信任模型（§3.5） ------------------------------------------------------------

@pytest.mark.parametrize("body", [
    '{"pi": {"bin": "/tmp/evil"}}',
    '{"pi": {"connector_path": "/tmp/evil.ts"}}',
    '{"pi": {"args": ["-e", "/tmp/evil.ts"]}}',
    '{"script": {"path": "/tmp/evil.jsonl"}}',
])
def test_project_user_only_keys_rejected(env, tmp_path, body):
    write_project(tmp_path, body)
    with pytest.raises(SettingsError, match="仅用户级"):
        resolve_settings(tmp_path / "t.pcl")


@pytest.mark.parametrize("dir_value", ["/abs/cache", "../escape"])
def test_project_cache_dir_escape_rejected(env, tmp_path, dir_value):
    write_project(tmp_path, json.dumps({"cache": {"dir": dir_value}}))
    with pytest.raises(SettingsError, match="cache.dir"):
        resolve_settings(tmp_path / "t.pcl")


def test_project_cache_dir_inside_ok(env, tmp_path):
    write_project(tmp_path, '{"cache": {"dir": ".gen-cache"}}')
    st = resolve_settings(tmp_path / "t.pcl")
    assert st.cache_dir == str((tmp_path / ".pcl" / ".gen-cache").resolve())


def test_user_level_execution_keys_allowed(env):
    write_user(env, '{"pi": {"bin": "/opt/pi"}, "script": {"path": "s.jsonl"}}')
    st = resolve_settings(None)
    assert st.pi_bin == "/opt/pi"
    assert st.script_path is not None and st.script_path.endswith("s.jsonl")


# ---- 相对路径与哨兵 ---------------------------------------------------------------

def test_relative_paths_resolve_against_settings_file(env):
    write_user(env, '{"pi": {"connector_path": "conn/index.ts"},'
                    ' "cache": {"dir": "cdir"}}')
    st = resolve_settings(None)
    base = Path(env) / "xdg" / "pcl"
    assert st.pi_connector_path == str(base / "conn" / "index.ts")
    assert st.cache_dir == str(base / "cdir")


def test_pi_bin_bare_name_and_separator(env):
    write_user(env, '{"pi": {"bin": "pi"}}')
    assert resolve_settings(None).pi_bin == "pi"      # 裸名交 PATH，不展开
    write_user(env, '{"pi": {"bin": "./bin/pi"}}')
    st = resolve_settings(None)
    assert st.pi_bin == str(Path(env) / "xdg" / "pcl" / "bin" / "pi")
    write_user(env, '{"pi": {"connector_path": "none"}}')
    assert resolve_settings(None).pi_connector_path == "none"   # 哨兵


# ---- 校验 ---------------------------------------------------------------------

def test_unknown_key_warns_and_strict_errors(env, capsys):
    write_user(env, '{"agant": "null"}')
    st = resolve_settings(None)
    assert "未知设置键 'agant'" in capsys.readouterr().err
    assert st.agent == "pi"
    write_user(env, '{"strict": true, "agant": "null"}')
    with pytest.raises(SettingsError, match="strict"):
        resolve_settings(None)


def test_type_errors(env):
    for body in ('{"agent": "bogus"}', '{"timeout": -1}', '{"timeout": "x"}',
                 '{"trace": "yes"}', '{"cache": {"keep_per_stem": 0}}',
                 '{"pi": {"args": [1]}}'):
        write_user(env, body)
        with pytest.raises(SettingsError):
            resolve_settings(None)


def test_bad_json_reports_line(env):
    write_user(env, '{\n  "agent": oops\n}')
    with pytest.raises(SettingsError) as ei:
        resolve_settings(None)
    assert ei.value.line == 2


def test_dollar_keys_ignored(env, capsys):
    write_user(env, '{"$schema": "x", "$comment": "y", "agent": "null"}')
    st = resolve_settings(None)
    assert st.agent == "null"
    assert "未知设置键" not in capsys.readouterr().err


def test_jsonc_user_file_with_comments(env):
    write_user(env, '// 注释\n{"agent": "null", // 调试\n}')
    assert resolve_settings(None).agent == "null"
