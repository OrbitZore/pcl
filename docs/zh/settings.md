# 设置

面向使用者。完整规则（信任模型、合并算法）：[RFC 0001 §8](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0001-runtime.zh.md)。

## 两层配置

| 层 | 路径 | 说明 |
|---|---|---|
| 用户级 | `~/.config/pcl/settings.json`（或 `$PCL_CONFIG_FILE`） | 你自己的环境 |
| 项目级 | 入口 `.pcl` 向上最近的 `.pcl/settings.json` | 随仓库分发 |

优先级：**命令行 > 项目级 > 用户级 > 内置默认**。

格式是 JSONC（支持 `//` 注释与尾随逗号）。

## 常用配置

```jsonc
{
  // 使用哪个 agent 桥：pi / null / script
  "agent": "pi",
  // 单 pass 超时（秒）
  "timeout": 900,
  // 默认开 --trace
  "trace": false,
  "cache": {
    "disable": false,       // true = 每次重新编译
    "dir": null,            // 自定义缓存目录（相对路径按设置文件所在目录解析）
    "keep_per_stem": 2
  }
}
```

**仅用户级可配**（安全限制，项目级出现即报错）：

```jsonc
{
  "pi": {
    "bin": "/usr/local/bin/pi",      // pi 可执行
    "connector_path": "~/pi/pcl-connector/pi",  // 连接器路径
    "args": ["--model", "glm-5.3"]   // 透传参数（数组逐层拼接）
  },
  "script": { "path": "replay.jsonl" }
}
```

> 为什么限制？项目级文件是 clone 即得的**不可信输入**——若允许它指定
> 可执行/扩展路径，等于仓库静默执行任意代码。行为参数（agent/timeout/
> trace/cache）项目级可配；执行面（pi.bin 等）仅用户级。

## 查看生效配置

```bash
pcl config            # 逐项打印值 + 来源（CLI/项目/用户/内置）
pcl config --defaults
```

## 环境变量

| 变量 | 作用 |
|---|---|
| `PCL_CONFIG_FILE` | 用户级设置重定向 |
| `PCL_NO_PROJECT_CONFIG` | 忽略项目级设置（密封运行） |
| `PCL_BIN` | 嵌入形态下连接器 spawn pcl 用 |
