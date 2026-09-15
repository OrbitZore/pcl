/**
 * pcl-connector — PCL 语言契约的 pi 侧实现（DESIGN §9）。
 *
 * 职责：
 * - `/pcl`：连接器唯一注册的命令（人类命令面板/补全只出现它）；
 *   - 机器子命令 `pass`（刻意不进补全）：每 pass 唯一信令——
 *     payload = `{"writable":[…],"reads":{…},"text":…}`（三键恒出现，
 *     args = pass 之后的原样余串、紧凑单行 JSON）；handler 登记
 *     白名单/快照后 `await pi.sendUserMessage(text)`（缺省不展开，
 *     `/` 开头 pass 文本免疫）——pass 文本永不裸发；
 *   - run/gen/check/version 子命令（嵌入形态）属 M3 里程碑；
 * - `pcl_write` / `pcl_read` 工具：写回通道（扩展侧先行拒绝非 writable
 *   名单并引导模型当轮重试）与读取通道（查快照本地应答，不经主机往返）；
 * - `before_agent_start`：仅当 read/write 名字存在时注入使用协议
 *   （systemPrompt 链式追加，不落会话）。
 *
 * 安装：复制/链接本文件到 ~/.pi/agent/extensions/（或其子目录），
 * 或由 pcl 经 `--connector-path` 直指本源文件（pi 经 jiti 直接加载 TS）。
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

interface PassState {
  writable: string[];
  reads: Record<string, unknown>;
}

let current: PassState | null = null;

const PASS_PREFIX = "/pcl pass ";

function toolText(text: string) {
  return { content: [{ type: "text" as const, text }], details: {} };
}

function passError(message: string): never {
  throw new Error(message);
}

/** 机器子命令：登记白名单/快照 + 提交文本（§8.2/§9.1）。 */
async function submitPass(payloadRaw: string, pi: ExtensionAPI): Promise<void> {
  let payload: any;
  try {
    payload = JSON.parse(payloadRaw);
  } catch (e) {
    passError(`pcl pass payload 非法 JSON：${e instanceof Error ? e.message : String(e)}`);
  }
  if (typeof payload !== "object" || payload === null || typeof payload.text !== "string") {
    passError("pcl pass payload 缺少 text（应为 {writable, reads, text}）");
  }
  current = {
    writable: Array.isArray(payload.writable) ? payload.writable : [],
    reads: (payload.reads && typeof payload.reads === "object") ? payload.reads : {},
  };
  // 缺省不展开：/ 开头文本原样入会话（信令与文本结构性分离，§8.2）
  await pi.sendUserMessage(payload.text);
}

export default function (pi: ExtensionAPI): void {
  pi.registerCommand("pcl", {
    description: "PCL：/pcl run <file.pcl> [PROMPT] — 在当前会话执行 PCL（与 pcl CLI 对齐）",
    getArgumentCompletions: (prefix: string) => {
      const subs = ["run", "gen", "check", "version"]
        .map((s) => ({ value: s, label: s }))
        .filter((i) => i.value.startsWith(prefix));
      return subs.length ? subs : null;
    },
    handler: async (args: string, ctx) => {
      const trimmed = args.trim();
      const sub = trimmed.split(/\s+/)[0] ?? "";
      if (sub === "pass") {
        return submitPass(trimmed.slice(4).trim(), pi);
      }
      // run/gen/check/version（嵌入形态）属 M3；给出用法提示
      const usage = [
        "PCL 用法：",
        "  /pcl run <file.pcl> [PROMPT…]   在当前会话执行 PCL（M3 交付）",
        "  /pcl gen|check <file.pcl>       生成源/编译检查（M3 交付）",
        "  /pcl version                    版本直通（M3 交付）",
      ].join("\n");
      ctx.ui.notify(usage, "info");
    },
  });

  pi.registerTool({
    name: "pcl_write",
    label: "PCL write",
    description:
      "把结构化值写回当前 pcl pass 的 PCL 变量。调用时传 "
      + '{"values": {变量名: JSON 值}}；只允许写 pass 声明的可写名单，'
      + "名单外调用会被拒绝（当轮改用正确名字重试）。",
    // pi@0.85.1 实测：顶层开放形状（Record/additionalProperties）会被参数
    // 校验层剥空，命名键承载完好——故经 values 嵌套（同时兼容平铺形态）。
    parameters: Type.Object({
      values: Type.Record(Type.String(), Type.Unknown(), {
        description: "要写入的 {变量名: JSON 值} 对象",
      }),
    }),
    async execute(_id, params) {
      if (!current) {
        return toolText("错误：当前没有进行中的 pcl pass。");
      }
      const raw = (params as any)?.values;
      const values: Record<string, unknown> =
        raw && typeof raw === "object" ? raw : (params as any) ?? {};
      const names = Object.keys(values);
      if (names.length === 0) {
        return toolText("错误：参数为空；应传 {\"values\": {变量名: 值}}。");
      }
      const bad = names.filter((n) => !current!.writable.includes(n));
      if (bad.length > 0) {
        const writable = current.writable.join(", ") || "（无）";
        return toolText(
          `错误：${bad.join(", ")} 不可写；本 pass 可写：${writable}。`
          + "请只写名单内的变量（需要多值时写 dict/list 到单个变量）。",
        );
      }
      return toolText(`已接受写入：${names.join(", ")}。`);
    },
  });

  pi.registerTool({
    name: "pcl_read",
    label: "PCL read",
    description: "读取当前 pcl pass 可读的 PCL 变量（快照值）。",
    parameters: Type.Object({
      names: Type.Optional(
        Type.Array(Type.String(), { description: "变量名列表；缺省=全部可读" }),
      ),
    }),
    async execute(_id, params) {
      const snap = current?.reads ?? {};
      const want = (params?.names as string[] | undefined) ?? Object.keys(snap);
      if (want.length === 0) {
        return toolText("当前 pass 无可读变量。");
      }
      const bad = want.filter((n) => !(n in snap));
      if (bad.length > 0) {
        const readable = Object.keys(snap).join(", ") || "（无）";
        return toolText(`错误：${bad.join(", ")} 不可读；可读：${readable}。`);
      }
      const out: Record<string, unknown> = {};
      for (const n of want) out[n] = snap[n];
      return toolText(JSON.stringify(out));
    },
  });

  pi.on("before_agent_start", async (event) => {
    if (!current) return;
    const lines: string[] = [];
    if (current.writable.length > 0) {
      lines.push(
        `当前 pcl pass 可写变量：${current.writable.join(", ")}；`
        + "用 pcl_write 工具传 {变量名: JSON 值} 写回（名单外会被拒绝）。",
      );
    }
    const readable = Object.keys(current.reads);
    if (readable.length > 0) {
      lines.push(
        `当前 pcl pass 可读变量：${readable.join(", ")}；`
        + "用 pcl_read 工具按名拉取（长内容不必拼进回复）。",
      );
    }
    if (lines.length === 0) return;
    lines.push("pass 结束时仍需给出文本回复（至少一句）。");
    // systemPrompt 链式追加：仅本 turn 生效、不落会话（§9.2“注入使用协议”）
    return { systemPrompt: `${event.systemPrompt}\n\n[pcl]\n${lines.join("\n")}` };
  });

  pi.on("agent_settled", async () => {
    // pass 边界：清登记（后续轮次不再暴露读写工具协议）
    current = null;
  });
}
