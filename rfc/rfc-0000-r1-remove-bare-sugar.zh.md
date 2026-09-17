---
Number: 0000-r1
Title: Remove the $prompt bare sugar
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Implementation: pclang ≥ 0.2.0（未发布期修订，无迁移版本）
Parent: rfc-0000-language
Language: 中文（权威稿；英文镜像见同名 .md）
---

# RFC 0000-r1 — 移除 `$prompt` 裸糖

## Summary

删除 `$prompt` 裸糖（原 ≡ `$(prompt)`）。此后模板内注入 prompt 一律
写 `$(prompt)`；源码中出现 `$prompt` 报 **L103** 并给出迁移指引。

## Motivation

1. **特例无必要**：语言里只有 `prompt` 一个名字有糖，其他变量都要
   `$(name)`——不对称、增加学习成本
2. **隐藏语义**：`$prompt` 与 shell 变量写法雷同，读者易误以为存在
   一类 `$name` 语法；实际上没有
3. **移除成本低**：项目未发布（0.2.0.dev0 代码态），无外部模板依赖；
   趁 alpha 前夜删除，避免发版后成为永久兼容包袱

## Specification

1. 词法层：`$` + 完整标识符恰为 `prompt` 不再展开为合并型插值，
   改为编译错误：

   ```
   t.pcl:1:4 [L103] 裸糖 $prompt 已移除：请改用 $(prompt)
   ```

2. 最长标识符匹配保留：`$prompts`、`$promptX`、`$prompté` 等不是
   `prompt`，不受影响（仍为普通文本）；`$$prompt` 经转义优先，输出
   字面 `$prompt`
3. `$(prompt)` / `${prompt}` 语义不变
4. RFC 0000 构造表删除"裸糖"行；错误码族扩为 L100–L103

## Drawbacks

- 两字符变六字符，模板略长
- 旧草稿模板（未发布）需机械替换 `$prompt` → `$(prompt)`

## Alternatives

- **保留糖并文档化**：拒绝——不对称特例一旦发布就难回收
- **泛化 `$name` 为通用糖**：拒绝——与 `$$` 转义、`$(`/`${` 的交互
  会显著复杂化词法，且鼓励把插值滥用成隐式模板变量

## References

- [RFC 0000](rfc-0000-language.zh.md)（本修订的父规范）
