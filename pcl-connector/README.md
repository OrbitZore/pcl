# pcl-connector — PCL 的 agent 后端连接器族

PCL 的桥接层抽象为多 agent 后端做准备（RFC 0001 §6：**其他 agent 工具只增适配子包**）。
每个子包是独立分发的 pi-package 风格扩展包，与 Python 主包（`pclang`）拆包发布、互不依赖。

## 后端子包

| 子包 | 状态 | 说明 |
|---|---|---|
| [`pi/`](pi/) | ✅ v0.2 | pi 适配（首个）：`/pcl` 命令族、pass 信令、嵌入运行与上下文接续 |
| （预留） | 规划中 | 其他 agent CLI 后端各自成子包（`claude-code/`、`gemini-cli/`、…），实现各自的语言契约侧 |

## 新增后端子包的约定

1. 一个子包一个目录：`<backend>/package.json`（`pi` 清单或约定目录）+ 扩展源码；
   无构建——宿主 agent 经 jiti 直接加载 TS（或按目标生态约定）；
2. 语言契约（pass 读写、上下文三指令、错误码族）以 [RFC 0000](../rfc/rfc-0000-language.zh.md) 为准，
   协议面冻结（R16）；后端差异（信令通道、会话语义）收敛在子包内；
3. Python 侧经 `pcl/bridge.py` 的 `IAgentBridge` 对应扩展（`--agent <backend>`），
   子包与桥一一对应、版本握手经 `/pcl version`；
4. 与主包同版本节奏（CHANGELOG 统一记录），分发名 `pcl-connector-<backend>`。

## 安装（以 pi 为例）

```bash
pi install /abs/path/to/pcl-connector/pi      # 本地路径（发布后 npm:/git: 源）
pi -e /abs/path/to/pcl-connector/pi           # 临时试用
```

详见 [pi/README.md](pi/README.md) 与主 [README](../README.md)。
