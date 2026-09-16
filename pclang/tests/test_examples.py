"""examples/ 全部用例的编译守护（CI 守护示例语法，等价 pcl check）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pcl.compiler import compile_source

EXAMPLES = Path(__file__).resolve().parent.parent.parent / "examples"


@pytest.mark.parametrize(
    "p", sorted(EXAMPLES.glob("*.pcl")), ids=lambda p: p.name)
def test_example_compiles(p):
    compile_source(p.read_text(encoding="utf-8"), str(p))


def test_examples_readme_lists_all():
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for p in sorted(EXAMPLES.glob("*.pcl")):
        assert p.name in readme, f"{p.name} 未列入 examples/README.md"
