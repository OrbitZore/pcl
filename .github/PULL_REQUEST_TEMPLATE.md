<!-- 感谢贡献！中文模板可自译；关键 checklist 双语并列。 -->

## What / 改了什么

<!-- 一两句话说清变更 -->

## Why / 为什么

<!-- 动机与背景；关联 issue 用 Fixes #N -->

## RFC

<!-- 新 feature 必填：链接对应 RFC（Draft/Accepted PR 需先于或同 PR 合入） -->
<!-- bugfix / docs / tests 填 N/A -->

- RFC: <!-- e.g. https://github.com/OrbitZore/pcl/pull/N (rfc-0003-…) -->
- 语义变更走修订 RFC（NNNN-rN）而非原地改写：☐ 已确认不需要

## Checklist / 检查清单

- [ ] `python -m pytest -m "not smoke_pi"` 通过
- [ ] `ruff check src tests` 通过
- [ ] 涉及桥接/连接器：`python -m pytest -m smoke_pi` 通过（需 pi + 模型）
- [ ] 涉及语言变更：`examples/*.pcl` 全部 `pcl check` 通过；README 示例语法面同步评审
- [ ] 文档双语文档同步（docs/zh + docs/en）
- [ ] RFC 双语同步（rfc-NNNN-*.zh.md + .md）；状态字段已更新
- [ ] CHANGELOG.md（Unreleased 节）已记条目
- [ ] 版本号未手工多处改动（单源 `pclang/src/pcl/_version.py`；package.json 由 CI 守护）
