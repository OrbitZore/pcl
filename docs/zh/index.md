# PCL — Prompt Control Language

编排 LLM agent 的模板语言：**模板层是 PCL，脚本层是真 Python**。

## 为什么选 PCL？

- **零锁定**：你的逻辑就是普通 Python——import 任何库、用任何工具
- **可读可调试**：`.pcl` 编译为带行号标注的可读 Python 源（`# pcl:N`），traceback 直指模板行
- **完整的 agent 控制**：结构化写回、会话上下文管理、多轮循环——都是一等语言构造
- **零依赖**：纯 Python ≥3.10，运行时不装任何第三方包

## 一分钟看懂

```text
${ROUND = 0}
${DONE = False}
${W = ""}
${MAX = 100}

${:while ROUND < MAX}
    ${ROUND = ROUND + 1}

    ${:new}
    ${:pass :write W}
    执行者（第 $(ROUND)/$(MAX) 轮）。新上下文——所需信息如下。
    任务目标：$(prompt)
    只调用一次 pcl_write 写入：{"W": "行动摘要"}

    ${:new}
    ${:pass :write W}
    检查者（第 $(ROUND)/$(MAX) 轮）。新上下文——依以下证据判断。
    任务目标：$(prompt)
    只调用一次 pcl_write 写入：{"W": {"done": true/false, "note": "理由"}}

    ${:if isinstance(W, dict) and W.get("done")}
        ${DONE = True}
        ${:break}
    ${:fi}
${:done}

${:if DONE}
$(# 🎉 目标在第 $(ROUND)/$(MAX) 轮达成#)
${:fi}
```

```bash
pcl run goal.pcl "创建 hello.txt，内容为 Hello PCL"
```

## 从这里开始

- **[快速开始](quickstart.md)**——安装、第一个模板、5 分钟跑通
- **[核心指南](guide.md)**——pass、写回、上下文、循环编排
- **[语言参考](language.md)**——速查表与语义细节
- **[CLI 手册](cli.md)**——run/gen/check/config 与退出码
- **[设置](settings.md)**——用户级/项目级配置
- **[示例](examples.md)**——可运行示例导览
- **[FAQ](faq.md)**——常见问题

## 生态

- 首个适配 agent：[pi](https://github.com/earendil-works/pi-coding-agent)
  （正向 CLI + 会话内 `/pcl` 嵌入双形态）
- 语言规范与实现契约：[RFC 目录](https://github.com/OrbitZore/pcl/tree/main/rfc)
- 参与贡献：[CONTRIBUTING](https://github.com/OrbitZore/pcl/blob/main/CONTRIBUTING.zh-CN.md)

## 许可证

[GPL-3.0](https://github.com/OrbitZore/pcl/blob/main/LICENSE)
