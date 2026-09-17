# 快速开始

5 分钟：安装 → 写第一个模板 → 看 agent 写回变量。

## 安装

```bash
pip install pclang        # 或：pipx install pclang / uvx pclang
```

要求 Python ≥ 3.10。`pclang` 是分发名，命令与 import 名都是 `pcl`。

## 第一个模板（无 agent）

新建 `hello.pcl`：

```text
${NAME = prompt or "世界"}

你好，$(NAME)！
现在是 ${import datetime; datetime.date.today().isoformat()}。
```

运行：

```bash
pcl run hello.pcl "PCL"
```

输出：

```text
你好，PCL！
现在是2026-09-17。
```

这里你已经用到了 PCL 的核心思想：

- `${…}` 里是**真 Python 语句**（赋值、import 都行）
- `$(…)` 把 Python 表达式的值**织入文本**
- `$prompt` 是模板收到的第一个位置参数（裸糖，等价 `$(prompt)`）

## 加上 agent：一个 pass

前提：安装了 [pi](https://github.com/earendil-works/pi-coding-agent)
并配置好模型。新建 `score.pcl`：

```text
${SCORE = 0}

${:pass :write SCORE}
请就以下主题写一句话，并把自评质量分（0-10 整数）调用 pcl_write 写入 SCORE：
$prompt

${:if SCORE >= 7}
✔ 质量达标（$(SCORE) 分）
${:else}
✘ 分数不够（$(SCORE) 分）
${:fi}
```

运行：

```bash
pcl run score.pcl "为什么天是蓝的"
```

发生了什么：

1. `${:pass :write SCORE}` 把下面的文本发给 agent（pi）
2. agent 调用 `pcl_write` 工具写回 `SCORE`
3. PCL 拿到写回值继续执行——`${:if SCORE >= 7}` 就是普通 Python 条件

**没有 agent 也能调试**：

```bash
pcl run --agent null score.pcl "测试"    # reply=prompt 原样，纯模板逻辑验证
```

## shebang 直执行

```bash
echo '#!/usr/bin/env pcl' | cat - score.pcl > score2.pcl
chmod +x score2.pcl
./score2.pcl "为什么草是绿的"
```

## 下一步

- [核心指南](guide.md)——pass 生命周期、`:new`/`:save`/`:load`、
  goal 循环、注记与上下文注入
- [语言参考](language.md)——全部构造速查
- 出错了？[FAQ](faq.md) 有错误码速查
