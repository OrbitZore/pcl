"""cli — pcl 命令行入口（DESIGN §10，DSL §11；设置文件见 docs/SETTINGS.md）。

``pcl run / gen / check / config / version``；退出码：0 成功；1 编译期（L/P/C）
与用法错（argparse 默认 2 覆写为 1）及**设置错误**；2 运行期（R）；3 桥接（A）；
130 SIGINT（R409）。

设置解析（CLI 层专用，库形态不受影响）：
- 显式 CLI 参数 > 项目级 > 用户级 > 内置默认（argparse 各旗标 ``default=None``
  以区分“显式给出”，事后走 fallback 链）；
- ``--pi-arg`` 项追加在设置 ``pi.args`` 之后；
- ``--cache none`` > 设置 ``cache.disable``；``--cache DIR`` > 设置 ``cache.dir``；
- ``--no-project-config`` / ``PCL_NO_PROJECT_CONFIG=1`` 跳过项目级发现。
"""

from __future__ import annotations

import argparse
import sys

from ._version import __version__


class _Parser(argparse.ArgumentParser):
    """argparse 默认用法错退出码 2 → 覆写为 1（§10）。"""

    def error(self, message):  # noqa: D102
        self.print_usage(sys.stderr)
        sys.stderr.write(f"pcl: 错误：{message}\n")
        sys.exit(1)

    def exit(self, status=0, message=None):  # --help 等正常退出保持 0
        if message:
            sys.stderr.write(message)
        sys.exit(1 if status == 2 else status)


def build_parser() -> _Parser:
    p = _Parser(prog="pcl", description="PCL — Prompt Control Language")
    p.add_argument("--version", action="version",
                   version=f"pcl {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="命令")

    def add_cache_opts(sp):
        sp.add_argument("--cache", dest="cache", default=None, metavar="DIR|none")
        sp.add_argument("--no-project-config", action="store_true",
                        help="跳过项目级设置发现（密封运行，SETTINGS §5-F）")

    run = sub.add_parser("run", help="编译并执行模板（加载 + main(prompt)）")
    run.add_argument("file", help="模板 .pcl 文件")
    run.add_argument("prompt", nargs="*", help="prompt 位置参数（以空格连接）")
    run.add_argument("--prompt", dest="prompt_opt", default=None,
                     help="prompt 同义选项（与位置参数冲突时以位置参数为准）")
    run.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                     help="注入模块全局（可多次；VALUE 先 literal_eval 失败按原串）")
    run.add_argument("--agent", default=None, choices=["pi", "null", "script", "embed"],
                     help="默认取自设置（缺省 pi）")
    run.add_argument("--script", metavar="PATH", help="script 桥回放文件（JSONL）")
    run.add_argument("--pi-bin", metavar="PATH")
    run.add_argument("--connector-path", metavar="PATH|none")
    run.add_argument("--pi-arg", action="append", default=[], metavar="ARG")
    run.add_argument("--timeout", type=float, default=None, metavar="SEC")
    run.add_argument("-o", "--output", dest="output", metavar="FILE",
                     help="只写文件，不再打 stdout")
    run.add_argument("--trace", action="store_true")
    add_cache_opts(run)

    gen = sub.add_parser("gen", help="打印生成的 Python 源")
    gen.add_argument("file")
    add_cache_opts(gen)

    chk = sub.add_parser("check", help="模板编译 + 生成源 compile() 检查（不执行）")
    chk.add_argument("file")
    add_cache_opts(chk)

    cfg = sub.add_parser("config",
                         help="打印生效设置及各键来源（文件层 + 内置默认；"
                              "CLI 显式参数不在此列）")
    cfg.add_argument("file", nargs="?",
                     help="可选 .pcl 入口（用于项目级设置发现）")
    cfg.add_argument("--no-project-config", action="store_true")
    cfg.add_argument("--defaults", action="store_true", help="仅打印内置默认")
    cfg.add_argument("--show-origin", action="store_true",
                     help="显示各键来源（默认已开启；git config 风格旗标兼容）")

    sub.add_parser("version", help="版本")
    return p


# ---- 设置回退链（CLI 显式 > 项目级 > 用户级 > 内置） ---------------------------

def _cache_kwargs(args_cache, settings):
    if args_cache == "none":
        return {"no_cache": True}
    if args_cache:
        return {"cache_dir": args_cache}
    if settings.cache_disable:
        return {"no_cache": True}
    if settings.cache_dir:
        return {"cache_dir": settings.cache_dir}
    return {}


def _parse_var(specs: list[str]) -> dict:
    """NAME=VALUE 按首个 = 切分；VALUE 先 ast.literal_eval、失败按原串（§10）。"""
    import ast

    out: dict[str, object] = {}
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"pcl: 错误：--var {spec!r} 缺少 '='（应为 NAME=VALUE）")
        name, _, value = spec.partition("=")
        if not name.isidentifier():
            raise SystemExit(f"pcl: 错误：--var 名 {name!r} 不是合法 Python 标识符")
        try:
            out[name] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            out[name] = value
    return out


def _format_config(settings, defaults_only: bool) -> str:
    from .settings import BUILTIN

    lines = []
    if defaults_only:
        lines.append("# 内置默认（--defaults）")
        flat = {"agent": BUILTIN["agent"], "timeout": BUILTIN["timeout"],
                "trace": BUILTIN["trace"], "strict": BUILTIN["strict"],
                "cache.dir": BUILTIN["cache"]["dir"],
                "cache.disable": BUILTIN["cache"]["disable"],
                "cache.keep_per_stem": BUILTIN["cache"]["keep_per_stem"],
                "pi.bin": BUILTIN["pi"]["bin"],
                "pi.connector_path": BUILTIN["pi"]["connector_path"],
                "pi.args": BUILTIN["pi"]["args"],
                "script.path": BUILTIN["script"]["path"]}
        for k, v in flat.items():
            lines.append(f"{k} = {json_dumps(v)}  # builtin")
        return "\n".join(lines) + "\n"

    lines.append("# 有效配置（文件层与内置默认；CLI 显式参数不在此列）")
    for k, v in settings.flat().items():
        origin = settings.origins.get(k, "builtin")
        lines.append(f"{k} = {json_dumps(v)}  # {origin}")
    for s in settings.sources:
        lines.append(f"# 来源：{s}")
    if not settings.sources:
        lines.append("# 来源：无设置文件（全部为内置默认）")
    return "\n".join(lines) + "\n"


def json_dumps(v) -> str:
    import json

    return json.dumps(v, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    # ``--`` 分隔符预处理（版本无关）：argparse 对子命令 + nargs="*" 位置参数
    # 的 ``--`` 语义随 Python 版本漂移（≤3.13 视为无法识别的参数、3.14 并入
    # 位置参数）——首个 ``--`` 后的 token 一律并入 PROMPT、自身移除（§10），
    # 与连接器侧 /pcl run 的切分规则一致（§9.1）。
    argv = list(sys.argv[1:] if argv is None else argv)
    extra_prompt: list[str] = []
    if argv and argv[0] == "run":
        if "--" in argv:
            i = argv.index("--")
            extra_prompt = argv[i + 1:]
            argv = argv[:i]
    try:
        args = build_parser().parse_args(argv)
        if args.cmd == "run":
            args.prompt = list(args.prompt) + extra_prompt
    except SystemExit as e:   # 用法错（argparse 2 → 1，§10）
        return int(e.code or 0) if e.code else 1

    from .errors import PclCompileError, PclError, exit_code_for
    from .settings import SettingsError, resolve_settings

    try:
        if args.cmd == "version":
            print(f"pcl {__version__}")
            return 0

        if args.cmd == "config":
            try:
                st = resolve_settings(args.file,
                                      no_project=args.no_project_config)
            except SettingsError as e:
                sys.stderr.write(f"pcl: 设置错误：{e.format()}\n")
                return 1
            sys.stdout.write(_format_config(st, args.defaults))
            return 0

        # run / gen / check：入口 .pcl 为设置发现基准（SETTINGS §2）
        try:
            settings = resolve_settings(args.file,
                                        no_project=args.no_project_config)
        except SettingsError as e:
            sys.stderr.write(f"pcl: 设置错误：{e.format()}\n")
            return 1

        if args.cmd == "gen":
            from .compiler import compile_program

            src = compile_program(args.file,
                                  **_cache_kwargs(args.cache, settings))
            sys.stdout.write(src)
            return 0

        if args.cmd == "check":
            from .compiler import compile_program

            src = compile_program(args.file,
                                  **_cache_kwargs(args.cache, settings))
            n = len(src.splitlines())
            print(f"OK: {args.file} 编译通过（生成 {n} 行 Python）")
            return 0

        if args.cmd == "run":
            from .runtime import run_program

            agent = args.agent or settings.agent
            if agent == "embed":
                if not args.output:
                    sys.stderr.write(
                        "pcl: 错误：--agent embed 强制 -o（嵌入形态 stdout 让给协议，§8.5；"
                        "通常由 pi 内 /pcl run 自动生成）\n")
                    return 1
                # stdout 协议独占：模板/用户 Python 的 stdout 重定向到 stderr
                sys.stdout = sys.stderr

            prompt = " ".join(args.prompt) if args.prompt else (
                args.prompt_opt or "")
            var_overrides = _parse_var(args.var)
            out = None
            out_fh = None
            if args.output:
                out_fh = open(args.output, "w", encoding="utf-8", newline="\n")
                out = lambda s: out_fh.write(s)  # noqa: E731
            try:
                result = run_program(
                    args.file, prompt,
                    agent=agent,
                    script=args.script or settings.script_path,
                    var_overrides=var_overrides,
                    pi_bin=args.pi_bin or settings.pi_bin,
                    connector_path=(args.connector_path
                                    or settings.pi_connector_path),
                    pi_args=settings.pi_args + list(args.pi_arg),
                    timeout=(args.timeout if args.timeout is not None
                             else settings.timeout),
                    trace=args.trace or settings.trace,
                    out=out,
                    **_cache_kwargs(args.cache, settings),
                )
                if out is None:
                    _stdout_write(result.output)
                else:
                    out_fh.flush()
                return 0
            finally:
                if out_fh:
                    out_fh.close()
        return 0
    except PclCompileError as e:
        sys.stderr.write(e.format() + "\n")
        return 1
    except SettingsError as e:
        sys.stderr.write(f"pcl: 设置错误：{e.format()}\n")
        return 1
    except PclError as e:
        sys.stderr.write(e.format() + "\n")
        return exit_code_for(e.code)
    except KeyboardInterrupt:
        sys.stderr.write("pcl: [R409] 用户中断\n")
        return 130
    except NotImplementedError as e:
        sys.stderr.write(f"pcl: 尚未实现：{e}\n")
        return 1
    except BrokenPipeError:
        return 0
    except OSError as e:
        sys.stderr.write(f"pcl: {e}\n")
        return 1


def _stdout_write(s: str):
    """输出统一 UTF-8（§10）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass
    sys.stdout.write(s)


if __name__ == "__main__":
    sys.exit(main())
