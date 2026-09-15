/**
 * pcl-connector — PCL 语言契约的 pi 侧实现（DESIGN §9；嵌入形态 §8.5）。
 *
 * 职责：
 * - `/pcl`：连接器唯一注册的命令（人类命令面板/补全只出现它）；
 *   - 机器子命令 `pass`（刻意不进补全）：每 pass 唯一信令——
 *     payload = `{"writable":[…],"reads":{…},"text":…}`（三键恒出现）；
 *     handler 登记白名单/快照后 `pi.sendUserMessage(text)`（缺省不展开，
 *     `/` 开头 pass 文本免疫）——pass 文本永不裸发；
 *   - `/pcl run <file.pcl> [PROMPT…] [选项…]`：嵌入当前会话运行——
 *     waitForIdle → spawn `pcl run … --agent embed -o <tmp>` 并代理协议；
 *   - `/pcl gen|check <file.pcl>`：纯编译直通（spawn 捕获 stdout）；
 *   - `/pcl version`：版本直通（协议握手，R16）；
 *   - 未知/缺省子命令 → 用法提示（不列 pass）；
 * - `pcl_write` / `pcl_read` 工具：写回通道（名单先行拒绝、引导当轮重试）
 *   与读取通道（查快照本地应答）；
 * - `before_agent_start`：仅当 read/write 名字存在时注入使用协议
 *   （systemPrompt 链式追加，不落会话）。
 *
 * 嵌入协议代理（§8.5 表，协议零新增、端点反转）：
 * - pcl → 连接器（JSONL 命令）：prompt（/pcl pass 信令 → 经模块级
 *   pi.sendUserMessage 入当前会话；提交失败合成 extension_error——失败可见性
 *   与正向形态同构）、get_state（合成 sessionFile）、get_commands（合成）、
 *   set_session_name（映射兼容，embed 下 pcl 不发）、new_session/switch_session
 *   （M3：reason=embed-ctx-unsupported → pcl A520；接续属 M4）、
 *   get_last_assistant_text（连接器缓存的末条 assistant text）、abort（ctx.abort）、
 *   未知命令 → success:false（pcl → A501，R16 版本深移护栏）；
 * - 事件转发：tool_execution_start（pcl_write 写值回流）、message_update
 *   （--trace）、message_end/turn_end（reply 兜底，每 pass 重置）、
 *   agent_settled（pass 边界）序列化写入 pcl stdin；
 * - 单活动桥：同一 pi 进程同时只允许一个嵌入 run（§8.6 总则 3）；
 * - 提交期失败检测：pi.sendUserMessage 为发后即忘且错误经 <runtime>
 *   extension_error 流出（扩展不可订阅）——以 agent_start 存活检测兜底，
 *   超时未启动即合成 command:pcl 错误事件 → pcl A501。
 *
 * 安装：复制/链接本文件到 ~/.pi/agent/extensions/（或其子目录），
 * 或由 pcl 经 `--connector-path` 直指本源文件（pi 经 jiti 直接加载 TS）。
 * 连接器仅 /pcl run 族需要宿主侧存在 pcl 可执行（PATH 解析，PCL_BIN 覆盖）。
 */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// ---- pass 登记（机器子命令 + 工具共享） ---------------------------------

interface PassState {
  writable: string[];
  reads: Record<string, unknown>;
}

let current: PassState | null = null;
/** 嵌入桥（单活动）；事件订阅经此转发给运行中的 pcl 子进程。 */
let embedBridge: EmbedBridge | null = null;
let latestPi: ExtensionAPI | null = null;

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
  pi.sendUserMessage(payload.text);
}

// ---- 嵌入桥（协议代理，§8.5） ----------------------------------------------

const NO_START_GRACE_MS = 15_000;   // 提交后未观测到 agent_start 的失败判定窗

class EmbedBridge {
  private proc: ChildProcess;
  private pi: ExtensionAPI;
  private ctx: ExtensionCommandContext;
  private pending = new Map<number, (r: any) => void>();
  private replyCache = "";
  private inPass = false;
  private agentStarted = false;
  private stderrTail: string[] = [];
  private startedAt = 0;
  done: Promise<number | null>;

  constructor(pi: ExtensionAPI, ctx: ExtensionCommandContext, proc: ChildProcess) {
    this.pi = pi;
    this.ctx = ctx;
    this.proc = proc;
    let resolveExit!: (code: number | null) => void;
    this.done = new Promise((res) => (resolveExit = res));

    let buf = "";
    proc.stdout!.setEncoding("utf-8");
    proc.stdout!.on("data", (chunk: string) => {
      buf += chunk;
      while (true) {
        const nl = buf.indexOf("\n");   // 仅按 \n 切分（U+2028/U+2029 免疫）
        if (nl === -1) break;
        let line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        if (!line.trim()) continue;
        this.handleLine(line).catch(() => { /* 写响应 EPIPE 安全 */ });
      }
    });
    proc.stderr!.setEncoding("utf-8");
    proc.stderr!.on("data", (chunk: string) => {
      this.stderrTail.push(chunk);
      if (this.stderrTail.length > 200) this.stderrTail.splice(0, 100);
    });
    proc.on("close", (code) => {
      const fail = { success: false, error: "pcl 子进程已退出" };
      for (const resolve of this.pending.values()) resolve(fail);
      this.pending.clear();
      resolveExit(code);
    });
  }

  stderr(): string {
    return this.stderrTail.join("").split(/\r?\n/).slice(-15).join("\n");
  }

  /** 全局事件订阅入口：序列化后写入 pcl stdin。 */
  forwardEvent(ev: any): void {
    if (ev.type === "message_end" || ev.type === "turn_end") {
      const msg = ev.message;
      if (msg?.role === "assistant" && this.inPass) {
        const text = assistantText(msg);
        if (text) this.replyCache = text;
      }
      this.write({ type: ev.type, message: { role: msg?.role, content: msg?.content } });
      return;
    }
    if (ev.type === "message_update") {
      this.write({ type: "message_update", assistantMessageEvent: ev.assistantMessageEvent });
      return;
    }
    if (ev.type === "agent_settled") {
      this.inPass = false;
      this.write({ type: "agent_settled" });
      return;
    }
    this.write(ev);   // tool_execution_start 等：原样转发
  }

  private write(obj: any): void {
    if (this.proc.stdin && !this.proc.stdin.destroyed) {
      try {
        this.proc.stdin.write(JSON.stringify(obj) + "\n");
      } catch { /* EPIPE：子进程将退出，A503 语义 */ }
    }
  }

  private ok(id: any, command: string, data?: any) {
    return { id, type: "response", command, success: true, ...(data ? { data } : {}) };
  }
  private fail(id: any, command: string, error: string, data?: any) {
    return { id, type: "response", command, success: false, error, ...(data ? { data } : {}) };
  }

  private async handleLine(line: string): Promise<void> {
    let cmd: any;
    try {
      cmd = JSON.parse(line);
    } catch {
      return;   // 坏帧：忽略（pcl 侧另有护栏）
    }
    const id = cmd.id;
    const respond = (resp: any) => this.write(resp);
    switch (cmd.type) {
      case "prompt": {
        const message = typeof cmd.message === "string" ? cmd.message : "";
        if (!message.startsWith(PASS_PREFIX)) {
          respond(this.fail(id, "prompt", "嵌入通道仅接受 /pcl pass 信令"));
          return;
        }
        let payload: any;
        try {
          payload = JSON.parse(message.slice(PASS_PREFIX.length));
        } catch {
          respond(this.fail(id, "prompt", "pcl pass payload 非法 JSON"));
          return;
        }
        current = {
          writable: Array.isArray(payload?.writable) ? payload.writable : [],
          reads: (payload?.reads && typeof payload.reads === "object") ? payload.reads : {},
        };
        this.replyCache = "";
        this.inPass = true;
        this.agentStarted = false;
        this.startedAt = Date.now();
        try {
          this.pi.sendUserMessage(payload.text);   // 发后即忘；settled 经事件转发
        } catch (err) {
          // 失败可见性（§8.5）：response 仍 ok、合成 extension_error → pcl A501
          this.write({
            type: "extension_error", extensionPath: "command:pcl", event: "command",
            error: `sendUserMessage 抛错：${err instanceof Error ? err.message : String(err)}`,
          });
        }
        respond(this.ok(id, "prompt"));
        return;
      }
      case "get_state": {
        const sessionFile = this.ctx.sessionManager.getSessionFile();
        respond(this.ok(id, "get_state", { sessionFile: sessionFile ?? null }));
        return;
      }
      case "get_commands": {
        const commands = (this.pi.getCommands() ?? []).map((c: any) => ({
          name: c.name, source: c.source,
        }));
        respond(this.ok(id, "get_commands", { commands }));
        return;
      }
      case "set_session_name": {
        // embed 下 pcl 不发（不重命名宿主会话，§8.3）；映射保留兼容
        try {
          this.pi.setSessionName(String(cmd.name ?? ""));
          respond(this.ok(id, "set_session_name"));
        } catch (err) {
          respond(this.fail(id, "set_session_name",
            err instanceof Error ? err.message : String(err)));
        }
        return;
      }
      case "new_session":
      case "switch_session": {
        // 会话替换会拆毁扩展实例——接续（接管/adoption）属 M4（§8.6）；
        // v0.1 协议 reason 语义见 §8.6 失败表：pcl 侧映射 A520
        respond(this.fail(id, cmd.type, "嵌入模式暂不支持会话替换（M4 接续）",
          { reason: "embed-ctx-unsupported" }));
        return;
      }
      case "get_last_assistant_text": {
        respond(this.ok(id, "get_last_assistant_text",
          { text: this.replyCache || null }));
        return;
      }
      case "abort": {
        try {
          this.ctx.abort();
          respond(this.ok(id, "abort"));
        } catch (err) {
          respond(this.fail(id, "abort",
            err instanceof Error ? err.message : String(err)));
        }
        return;
      }
      default:
        // 未知命令：success:false（pcl → A501；R16 版本深移护栏）
        respond(this.fail(id, cmd.type ?? "unknown", `未知命令：${cmd.type}`));
    }
  }

  /** agent_start 存活观测（提交期失败检测，§8.5 失败可见性兜底）。 */
  noteAgentStart(): void {
    this.agentStarted = true;
  }

  /** 提交后未观测到 agent_start 且未 settled → 合成失败事件（→ pcl A501）。 */
  checkLiveness(): void {
    if (!this.inPass || this.agentStarted) return;
    if (Date.now() - this.startedAt < NO_START_GRACE_MS) return;
    this.inPass = false;
    this.write({
      type: "extension_error", extensionPath: "command:pcl", event: "command",
      error: "pass 提交后未见 agent 启动（无模型/鉴权失败/宿主拒绝？）",
    });
  }
}

function assistantText(msg: any): string {
  if (typeof msg?.content === "string") return msg.content;
  if (!Array.isArray(msg?.content)) return "";
  return msg.content
    .filter((b: any) => b?.type === "text" && typeof b.text === "string")
    .map((b: any) => b.text)
    .join("");
}

// ---- /pcl run 族（§9.1） ----------------------------------------------------

const FORWARD_ONLY = ["--agent", "--pi-bin", "--connector-path", "--pi-arg", "--script"];

function pclBin(): string {
  return process.env.PCL_BIN ?? "pcl";
}

/** 解析 run 参数：file + PROMPT（到首个选项 token 前；字面 -- 并入其后 token）
 * + 选项尾（透传 pcl）；正向专属选项拒绝（§9.1）。 */
function parseRunArgs(
  tokens: string[],
): { file: string; prompt: string[]; opts: string[] } | { error: string } {
  if (tokens.length === 0) return { error: "缺少 <file.pcl>" };
  const file = tokens[0];
  if (!file.endsWith(".pcl")) return { error: `文件须为 .pcl：${file}` };
  const prompt: string[] = [];
  let opts: string[] = [];
  for (let i = 1; i < tokens.length; i++) {
    const t = tokens[i];
    if (t === "--") {                 // argparse 语义：其后 token 一并入 PROMPT
      prompt.push(...tokens.slice(i + 1));
      break;
    }
    if (t.startsWith("-") && t !== "-") {
      opts = tokens.slice(i);
      break;
    }
    prompt.push(t);
  }
  for (const o of opts) {
    const name = o.split("=")[0];
    if (FORWARD_ONLY.includes(name)) {
      return { error: `正向专属选项 ${name} 在嵌入形态被拒（请用正向 CLI）` };
    }
  }
  return { file, prompt, opts };
}

function spawnCapture(args: string[]): Promise<{ code: number | null; out: string; err: string }> {
  return new Promise((resolve) => {
    let out = "";
    let err = "";
    try {
      const p = spawn(pclBin(), args, { stdio: ["ignore", "pipe", "pipe"] });
      p.stdout!.setEncoding("utf-8");
      p.stdout!.on("data", (c: string) => (out += c));
      p.stderr!.setEncoding("utf-8");
      p.stderr!.on("data", (c: string) => (err += c));
      p.on("error", (e) => resolve({ code: null, out, err: err + String(e) }));
      p.on("close", (code) => resolve({ code, out, err }));
    } catch (e) {
      resolve({ code: null, out, err: String(e) });
    }
  });
}

const WIDGET_MAX_LINES = 120;

function presentWidget(ctx: ExtensionCommandContext, title: string, lines: string[]) {
  const body = lines.length > WIDGET_MAX_LINES
    ? [...lines.slice(0, WIDGET_MAX_LINES), `…（共 ${lines.length} 行，已截断）`]
    : lines;
  ctx.ui.setWidget("pcl-run", [`--- ${title} ---`, ...body], "aboveEditor");
}

async function runEmbedded(ctx: ExtensionCommandContext, tokens: string[]): Promise<void> {
  const parsed = parseRunArgs(tokens);
  if ("error" in parsed) {
    ctx.ui.notify(`pcl run：${parsed.error}`, "error");
    return;
  }
  const { file, prompt, opts } = parsed;
  if (embedBridge) {
    ctx.ui.notify("已有 /pcl run 进行中，请等待其结束（或改用正向 CLI）", "warning");
    return;
  }
  // 输出文件：用户显式 -o 透传；缺省生成临时文件（§8.5）
  const userOut = extractOutPath(opts);
  const workdir = userOut ? null : mkdtempSync(join(tmpdir(), "pcl-embed-"));
  const outPath = userOut ?? join(workdir!, "output.txt");

  await ctx.waitForIdle();
  const args = ["run", file, ...prompt, "--agent", "embed", "-o", outPath, ...opts];
  ctx.ui.setStatus("pcl", `pcl 运行中：${file}`);
  let proc: ChildProcess;
  try {
    proc = spawn(pclBin(), args, { stdio: ["pipe", "pipe", "pipe"] });
  } catch (e) {
    ctx.ui.setStatus("pcl", undefined as any);
    ctx.ui.notify(`无法启动 pcl（${pclBin()}；可用 PCL_BIN 覆盖）：${e}`, "error");
    return;
  }
  const bridge = new EmbedBridge(latestPi!, ctx, proc);
  embedBridge = bridge;
  const liveness = setInterval(() => bridge.checkLiveness(), 1000);
  try {
    const code = await bridge.done;
    const output = safeRead(outPath);
    if (code === 0) {
      presentWidget(ctx, `pcl run 完成（退出码 0）：${file}`, output.split("\n"));
      ctx.ui.notify(`pcl run 完成（退出码 0）`, "info");
    } else {
      const tail = bridge.stderr().trim();
      presentWidget(ctx, `pcl run 失败（退出码 ${code ?? "?"}）：${file}`, [
        ...output.split("\n"),
        ...(tail ? ["--- stderr 尾部 ---", ...tail.split("\n")] : []),
      ]);
      ctx.ui.notify(`pcl run 失败（退出码 ${code ?? "?"}）`, "error");
    }
  } finally {
    clearInterval(liveness);
    embedBridge = null;
    ctx.ui.setStatus("pcl", undefined as any);
    if (workdir) {
      try { rmSync(workdir, { recursive: true, force: true }); } catch { /* 尽力 */ }
    }
  }
}

function extractOutPath(opts: string[]): string | null {
  for (let i = 0; i < opts.length; i++) {
    if (opts[i] === "-o" || opts[i] === "--output") return opts[i + 1] ?? null;
    if (opts[i].startsWith("--output=")) return opts[i].slice("--output=".length);
    if (opts[i].startsWith("-o=")) return opts[i].slice(3);
  }
  return null;
}

function safeRead(path: string): string {
  try {
    return readFileSync(path, "utf-8");
  } catch {
    return "";
  }
}

async function passthrough(ctx: ExtensionCommandContext, tokens: string[]): Promise<void> {
  const { code, out, err } = await spawnCapture(tokens);
  if (code === 0) {
    presentWidget(ctx, `pcl ${tokens[0]}（退出码 0）`, out.split("\n"));
    ctx.ui.notify(`pcl ${tokens[0]} 完成`, "info");
  } else {
    presentWidget(ctx, `pcl ${tokens[0]}（退出码 ${code ?? "?"}）`, [
      ...out.split("\n"),
      ...(err.trim() ? ["--- stderr 尾部 ---", ...err.trim().split("\n").slice(-15)] : []),
    ]);
    ctx.ui.notify(`pcl ${tokens[0]} 失败（退出码 ${code ?? "?"}）`, "error");
  }
}

function usage(ctx: ExtensionCommandContext): void {
  ctx.ui.notify([
    "PCL 用法：",
    "  /pcl run <file.pcl> [PROMPT…] [选项]   在当前会话执行 PCL",
    "  /pcl gen|check <file.pcl>              生成源 / 编译检查",
    "  /pcl version                           版本",
    "  选项透传 pcl CLI（--var/--timeout/--trace/--cache/-o 等）；",
    "  正向专属选项（--agent/--pi-bin/--connector-path/--pi-arg/--script）被拒。",
  ].join("\n"), "info");
}

// ---- 扩展入口 ---------------------------------------------------------------

export default function (pi: ExtensionAPI): void {
  latestPi = pi;

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
      if (sub === "run") {
        return runEmbedded(ctx, trimmed.split(/\s+/).slice(1));
      }
      if (sub === "gen" || sub === "check" || sub === "version") {
        return passthrough(ctx, trimmed.split(/\s+/));
      }
      return usage(ctx);
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
        + "用 pcl_write 工具传 {\"values\": {变量名: JSON 值}} 写回（名单外会被拒绝）。",
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

  // 事件泵：pass 登记 + 嵌入转发（F7：只有当前会话实例收到事件）
  pi.on("agent_start", async () => {
    embedBridge?.noteAgentStart();
  });
  pi.on("agent_settled", async () => {
    current = null;   // pass 边界：清登记（后续轮次不再暴露读写工具协议）
    embedBridge?.forwardEvent({ type: "agent_settled" });
  });
  pi.on("tool_execution_start", async (event) => {
    embedBridge?.forwardEvent({
      type: "tool_execution_start",
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      args: event.args,
    });
  });
  pi.on("message_update", async (event) => {
    embedBridge?.forwardEvent(event);
  });
  pi.on("message_end", async (event) => {
    embedBridge?.forwardEvent(event);
  });
  pi.on("turn_end", async (event) => {
    embedBridge?.forwardEvent(event);
  });
}
