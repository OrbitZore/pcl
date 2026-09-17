"""importer 测试：hook、双向 import、.py 优先、加载层、隔离（RFC 0000 §9）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import pcl
from pcl.importer import import_from_path, install_importer
from pcl.runtime import run_program


@pytest.fixture
def on_path(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---- Python → DSL ----------------------------------------------------------

def test_hook_import_and_alias(on_path):
    write(on_path / "greet.pcl",
          '${GREETING = "hello"}\n'
          '${:function greet}\n$(GREETING.title()), $(prompt)!\n${:endfunction}\n')
    install_importer()
    import greet as g
    assert g.GREETING == "hello"
    assert hasattr(g, "main")
    from greet import greet as hello  # from-import + as
    chunks = []
    with pcl.Run(agent="null", out=chunks.append):
        hello("pcl")            # 函数内 emit 需 Run 上下文（无 Run → R405）
    assert "".join(chunks) == "Hello, pcl!\n"


def test_hook_py_priority(on_path):
    write(on_path / "both.pcl", "wrong\n")
    write(on_path / "both.py", "X = 'py'\n")
    install_importer()
    import both
    assert both.X == "py"


def test_hook_import_error_carry_diagnostics(on_path):
    write(on_path / "bad.pcl", "${x =}\n")
    install_importer()
    with pytest.raises(ImportError, match="C310"):
        import bad  # noqa: F401


def test_import_module_programmatic(on_path):
    write(on_path / "m.pcl", "${N = 41}\n")
    mod = pcl.import_module("m")
    assert mod.N == 41
    assert sys.modules["m"] is mod


def test_import_never_runs_template_body(on_path, capsys):
    write(on_path / "side.pcl", "TEXT never emitted\n${:pass}\nnever\n")
    install_importer()
    import side  # noqa: F401
    assert capsys.readouterr().out == ""


# ---- DSL → DSL ---------------------------------------------------------------

def test_dsl_to_dsl_import(on_path):
    write(on_path / "helpers.pcl",
          '${TITLE = "lib"}\n${:function shout}\n$(TITLE): $(prompt)\n${:endfunction}\n')
    write(on_path / "main.pcl",
          "${import helpers as h}\n${x = h.TITLE}\nR=$(x)\n")
    result = run_program(str(on_path / "main.pcl"), "", agent="null",
                         cache_dir=str(on_path / "cache"))
    assert result.output == "R=lib\n"


# ---- 包内相对 import（__package__ 按源目录） ------------------------------------

def test_package_relative_import(on_path):
    pkg = on_path / "pkg"
    pkg.mkdir()
    write(pkg / "__init__.py", "")
    write(pkg / "leaf.py", "V = 'leaf'\n")
    write(pkg / "tpl.pcl", "${from . import leaf}\n${:function get}\n$(leaf.V)\n${:endfunction}\n")
    install_importer()
    import pkg.tpl
    chunks = []
    with pcl.Run(agent="null", out=chunks.append):
        pkg.tpl.get("")
    assert "".join(chunks) == "leaf\n"


# ---- run_program 模块实例隔离（§6） ---------------------------------------------

def test_run_isolation(tmp_path):
    write(tmp_path / "counter.pcl", "${CNT = 0}${CNT = CNT + 1}CNT=$(CNT)\n")
    r1 = run_program(str(tmp_path / "counter.pcl"), "", agent="null",
                     cache_dir=str(tmp_path / "c"))
    r2 = run_program(str(tmp_path / "counter.pcl"), "", agent="null",
                     cache_dir=str(tmp_path / "c"))
    assert r1.output == "CNT=1\n"
    assert r2.output == "CNT=1\n"
    assert r1.module is not r2.module
    assert r1.module.CNT == 1 and r2.module.CNT == 1


def test_import_from_path_not_in_sys_modules(tmp_path):
    p = write(tmp_path / "iso.pcl", "${A = 1}\n")
    mod = import_from_path(p)
    assert mod.A == 1
    assert mod.__name__ not in sys.modules
    assert mod.__file__ == str(p)
    assert mod.__pcl_source__ == str(p)


# ---- sys.path 入口行为 -----------------------------------------------------------

def test_run_inserts_source_dir(tmp_path):
    libdir = tmp_path / "proj"
    libdir.mkdir()
    write(libdir / "dep.pcl", "${D = 7}\n")
    write(libdir / "app.pcl", "${import dep}\nD=$(dep.D)\n")
    r = run_program(str(libdir / "app.pcl"), "", agent="null",
                    cache_dir=str(tmp_path / "cache"))
    assert r.output == "D=7\n"
    assert str(libdir) in sys.path


def test_install_importer_idempotent():
    from pcl.importer import _PclMetaFinder
    install_importer()
    install_importer()
    n = sum(isinstance(f, _PclMetaFinder) for f in sys.meta_path)
    assert n == 1


def test_run_program_installs_importer_subprocess(tmp_path):
    """独立进程回归：pcl run 内建 importer（此前靠测试进程内泄漏的 hook 通过）。"""
    import subprocess

    pcl_bin = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "pcl"
    if not pcl_bin.exists():  # pragma: no cover
        pytest.skip("未找到 pcl 可执行")
    write(tmp_path / "helpers.pcl",
          '${H = "来自共享库"}\n${:function val}\n${:return H}\n${:endfunction}\n')
    write(tmp_path / "main.pcl", "${import helpers}\nR=$(helpers.val())\n")
    proc = subprocess.run(
        [str(pcl_bin), "run", str(tmp_path / "main.pcl"), "--agent", "null",
         "--cache", "none"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "R=来自共享库\n"
