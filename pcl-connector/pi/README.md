# pcl-connector-pi

[PCL](../../../README.md) 的 **pi** 连接器（agent 后端适配子包）：在 pi 会话内提供
`/pcl` 命令族与 `pcl_write`/`pcl_read` 工具，承载 pass 信令、嵌入运行与上下文接续。
正向形态（`pcl run --agent pi` 拉起 `pi --mode rpc`）与本包一体——同一扩展、两种端点（DESIGN §8/A13）。

## 安装

```bash
# ① pi 包安装（推荐；本地路径——相对 settings 解析，不复制）
pi install /path/to/pcl-connector/pi
#    发布后：pi install npm:pcl-connector-pi   /   pi install git:github.com/OrbitZore/pcl

# ② 临时试用（不写 settings，本次运行生效）
pi -e /path/to/pcl-connector/pi

# ③ 预装：复制/链接本目录到 ~/.pi/agent/extensions/
#    （如 pcl-connector-pi -> /path/to/pcl-connector/pi/extensions）
```

宿主侧还需 `pcl` 可执行（PATH 解析，`PCL_BIN` 可覆盖）——仅 `/pcl run` 族需要；
纯 pass 交互（正向 `--agent pi`）无此依赖。

## 卸载 / 更新

```bash
pi remove pcl-connector-pi            # 或源路径形态
pi update --extensions                # 更新全部包（git ref 复核）
```

## 功能

- `/pcl run <file.pcl> [PROMPT…] [选项]`：嵌入当前会话执行（waitForIdle → spawn
  `pcl --agent embed -o <tmp>` → 协议代理 → 呈现输出与退出码）；选项透传 pcl CLI，
  正向专属选项（`--agent/--pi-bin/--connector-path/--pi-arg/--script`）被拒
- `/pcl gen|check <file.pcl>`、`/pcl config [file]`、`/pcl version`：直通
- `/pcl pass {writable,reads,text}`：机器子命令（不进补全）——pass 唯一信令
- 工具：`pcl_write`（名单校验，参数经 `values` 键承载）、`pcl_read`（快照本地应答）
- 嵌入上下文接续（§8.6）：模块级桥、接管规则、auto-follow、孤儿路径、A520–A523

## 兼容性

pi ≥ 0.85（依赖 `SessionManager.open/getCwd`、`session_shutdown.reason`、
`ReplacedSessionContext`；契约见 [RFC 0002 §7](../../../rfc/rfc-0002-connector.zh.md)）。
协议版本随主包 `/pcl version` 握手（R16）。
