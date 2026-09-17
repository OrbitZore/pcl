# pclang — PCL：Prompt Control Language

编排 LLM/agent 的模板 DSL：**模板层是 PCL，脚本层是真 Python**。

- 纯 Python 包（≥3.10，运行时零第三方依赖），把 `.pcl` 编译成可读 Python 源并在同一解释器执行，完整复用 Python 生态；
- 首个适配的外部 agent 为 [pi](https://github.com/earendil-works/pi-coding-agent)：正向 `pcl run` 拉起 `pi --mode rpc` 经 stdio JSONL 驱动 [pcl-connector](https://github.com/OrbitZore/pcl) 完成pass 交互与上下文管理；反向亦通——pi 会话内 `/pcl run` 直接执行（嵌入模式）。

## 安装

```bash
pip install pclang     # 或 pipx install pclang / uvx pclang（分发名 pclang，命令与 import 名仍为 pcl）
```

## 一分钟看懂

```text
${SCORE = 0}

${:pass :write SCORE}
请就以下主题写一段话，并把自评质量分（0..10 整数）写入 SCORE：
$(prompt)

${:if SCORE >= 7}
质量达标，结束。
${:else}
分数不够，重写一遍，把新分数写入 SCORE。
${:fi}
```

```bash
pcl run demo.pcl "猫为什么会打呼噜"          # 默认 --agent pi（需已配置模型）
pcl run demo.pcl "主题" --agent null         # 纯模板调试（reply=prompt 原文）
pcl gen demo.pcl                            # 查看生成的 Python 源（含 # pcl:行号）
pcl check demo.pcl                          # 编译 + 语法检查
```

要点：表达式/语句/库全部是 Python——插值双形式 `${}`（发起型：冲刷保序、独立 emit）/`$()`（合并型：立即求值织入段落）；控制流用 `:if…:fi`、`:for|:while…:done` 指令对；`:pass :read/:write 名字` 开启一轮 agent 交互，回复进输出并存入 `reply`；上下文三指令 `:save/:load/:new`（token=pi 会话文件，跨运行自己保管）；`.pcl` 即 Python 模块（`import pcl; pcl.install_importer()` 后可直接 `import mytpl`，import 永不触发 agent）。

## pi 连接器（正向 `--agent pi`）

主包不含连接器（拆包分发；多后端连接器族见 [pcl-connector/](https://github.com/OrbitZore/pcl/tree/main/pcl-connector/)）。安装三选一：

1. **pi 包**：`pi install /path/to/pcl-connector/pi`（`pi -e` 同路径临时试用；`pi remove` 卸载）；
2. **预装**：复制/链接 `pcl-connector/pi/extensions` 到 `~/.pi/agent/extensions/`——`--connector-path` 缺省 `none` 即用；
3. **运行时直指**：`--connector-path /path/to/pcl-connector/pi`（包目录或 `extensions/index.ts`）。

## 文档

- 规范与实现契约：[RFC 0000 语言](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0000-language.zh.md) · [RFC 0001 执行层](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0001-runtime.zh.md) · [RFC 0002 连接器](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0002-connector.zh.md)

## 许可

GPL-3.0
