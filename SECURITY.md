# Security Policy / 安全策略

English | 中文

## Supported Versions / 支持版本

| Version | Supported |
|---|---|
| pre-1.0 (0.2.0aN+) | ✅ latest only |

## Reporting a Vulnerability / 报告漏洞

**Please do not open public issues for security problems.**
请勿为安全问题开公开 issue。

Use [GitHub private vulnerability reporting](
https://github.com/OrbitZore/pcl/security/advisories/new)，
或联系维护者。我们会在 7 天内确认收到；修复按严重程度排期，
修复后在 CHANGELOG 与 GitHub Security Advisories 公告。

## Trust Model / 信任模型（必读）

PCL 的供应链防线（完整定义见
[RFC 0001 §8](rfc/rfc-0001-runtime.zh.md)）：

- **项目级 `.pcl/settings.json` 是不可信输入**（clone 即得）：
  `pi.bin`、`pi.connector_path`、`pi.args`、`script.path` 等执行面键
  **仅允许用户级配置**；项目级出现即报错退出
- **`~/.pcl/bin/` 下的脚本以 embedded 方式在你当前会话运行**——
  只放置你信任来源的 `.pcl` 脚本（等价于把任意 prompt 交给你的
  agent 会话）
- **连接器安装来源**：`pi install` 支持 git/npm/本地路径——只安装
  你信任的来源；连接器代码在你的 pi 会话内运行
- `.pcl` 模板内是**真 Python**：执行任意 `.pcl` 文件等价于执行
  Python 脚本——与运行 `pip install` 或 `bash` 脚本同等对待

## Scope / 范围

- ✅ 编译器与运行时（`pclang`）、连接器（`pcl-connector/`）、
  设置信任模型、协议实现
- ❌ 你的 LLM 提供商、pi 本体（报告至
  [pi 仓库](https://github.com/earendil-works/pi-coding-agent)）、
  agent 生成内容本身
