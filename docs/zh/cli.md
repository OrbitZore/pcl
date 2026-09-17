# CLI 手册

命令名 `pcl`（分发名 `pclang`）；`python -m pcl` 等价。

## pcl run

```bash
pcl run <file.pcl> [PROMPT…] [选项]
```

| 选项 | 说明 |
|---|---|
| `--agent NAME` | `pi`（默认，真实 agent）/ `null`（reply=prompt，调试）/ `script`（JSONL 回放） |
| `-o FILE` | 输出文档写到 FILE（缺省 stdout） |
| `--trace` | stderr 流式诊断：pass 提交、思考增量、pcl_write、轮次边界 |
| `--cache none\|dir` | 缓存策略（缺省按设置） |
| `--pi-bin PATH` / `--pi-arg ARG` | pi 可执行与透传参数（可重复） |
| `--script-path FILE` | script 桥回放文件 |
| `--timeout SEC` | 单 pass 超时 |

位置参数成为模板内的 `prompt` 变量（多个参数空格连接）。

### shebang 直执行

首行 `#!/usr/bin/env pcl` + `chmod +x`：

```bash
./goal.pcl "任务描述"
```

## pcl gen / pcl check

```bash
pcl gen file.pcl        # 打印生成的 Python 源（含 # pcl:N 行号标注）
pcl check file.pcl      # 仅编译校验
```

排查"模板到底生成了什么代码"的第一工具。

## pcl config

```bash
pcl config              # 打印生效配置及每项来源（CLI/项目/用户/内置）
pcl config --defaults   # 内置默认
```

## pcl version

版本号 + 协议握手信息（执行层与目标连接器路径）。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 编译期错误（L/P/C 类） |
| 2 | 运行期错误（R 类） |
| 3 | 桥接错误（A 类） |
| 130 | 用户中断（Ctrl-C） |

## 缓存

- 位置：`$XDG_CACHE_HOME/pcl`（缺省 `~/.cache/pcl`）
- 命名 `<stem>-<sha8>.pcl.py`；原子写入；同 stem 保留 2 条
- 改了模板自动重编译（内容哈希变化即 miss）

## 调试技巧

```bash
pcl gen file.pcl | less          # 看生成代码
pcl run --agent null file.pcl    # 不调 agent 跑模板逻辑
pcl run --trace file.pcl 2>trace.log   # 全程留痕
```
