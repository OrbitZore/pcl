"""cli — pcl 命令行入口（DESIGN §10，DSL §11）。

``pcl run / gen / check / version``；退出码：0 成功；1 编译期（L/P/C）与用法错
（argparse 默认 2 一律覆写为 1）；2 运行期（R）；3 桥接（A）；130 SIGINT（R409）。
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

    run = sub.add_parser("run", help="编译并执行模板（加载 + main(prompt)）")
    run.add_argument("file", help="模板 .pcl 文件")
    run.add_argument("prompt", nargs="*", help="prompt 位置参数（以空格连接）")
    run.add_argument("--prompt", dest="prompt_opt", default=None,
                     help="prompt 同义选项（与位置参数冲突时以位置参数为准）")
    run.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                     help="注入模块全局（可多次；VALUE 先 literal_eval 失败按原串）")
    run.add_argument("--agent", default="pi", choices=["pi", "null", "script", "embed"])
    run.add_argument("--script", metavar="PATH", help="script 桥回放文件（JSONL）")
    run.add_argument("--pi-bin", metavar="PATH")
    run.add_argument("--connector-path", metavar="PATH|none", default="none")
    run.add_argument("--pi-arg", action="append", default=[], metavar="ARG")
    run.add_argument("--timeout", type=float, default=300.0, metavar="SEC")
    run.add_argument("-o", "--output", dest="output", metavar="FILE",
                     help="只写文件，不再打 stdout")
    run.add_argument("--trace", action="store_true")
    run.add_argument("--cache", dest="cache", default=None, metavar="DIR|none")

    gen = sub.add_parser("gen", help="打印生成的 Python 源")
    gen.add_argument("file")
    gen.add_argument("--cache", dest="cache", default=None, metavar="DIR|none")

    chk = sub.add_parser("check", help="模板编译 + 生成源 compile() 检查（不执行）")
    chk.add_argument("file")
    chk.add_argument("--cache", dest="cache", default=None, metavar="DIR|none")

    sub.add_parser("version", help="版本")
    return p


def _cache_kwargs(cache: str | None) -> dict:
    if cache is None:
        return {}
    if cache == "none":
        return {"no_cache": True}
    return {"cache_dir": cache}


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


def main(argv: list[str] | None = None) -> int:
    from .errors import PclCompileError, PclError, exit_code_for

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:   # 用法错（argparse 2 → 1，§10）
        return int(e.code or 0) if e.code else 1

    try:
        if args.cmd == "version":
            print(f"pcl {__version__}")
            return 0

        if args.cmd == "gen":
            from .compiler import compile_program

            src = compile_program(args.file, **_cache_kwargs(args.cache))
            sys.stdout.write(src)
            return 0

        if args.cmd == "check":
            from .compiler import compile_program

            src = compile_program(args.file, **_cache_kwargs(args.cache))
            n = len(src.splitlines())
            print(f"OK: {args.file} 编译通过（生成 {n} 行 Python）")
            return 0

        if args.cmd == "run":
            from .runtime import run_program

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
                    agent=args.agent,
                    script=args.script,
                    var_overrides=var_overrides,
                    pi_bin=args.pi_bin,
                    connector_path=args.connector_path,
                    pi_args=args.pi_arg,
                    timeout=args.timeout,
                    trace=args.trace,
                    out=out,
                    **_cache_kwargs(args.cache),
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
