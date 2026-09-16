/**
 * pcl-connector — PCL 语言契约的 pi 侧实现（DESIGN §9；嵌入形态 §8.5–8.6）。
 *
 * 职责：
 * - `/pcl`：连接器唯一注册的命令（人类命令面板/补全只出现它）；
 *   - 机器子命令 `pass`（刻意不进补全）：每 pass 唯一信令——
 *     payload = `{"writable":[…],"reads":{…},"text":…}`（三键恒出现）；
 *     handler 登记白名单/快照后经模块级 `pi.sendUserMessage(text)` 入当前会话
 *     （缺省不展开，`/` 开头 pass 文本免疫）——pass 文本永不裸发；
 *   - `/pcl run <file.pcl> [PROMPT…] [选项…]`：嵌入当前会话运行——
 *     waitForIdle → spawn `pcl run … --agent embed -o <tmp>` 并代理协议；
 *   - `/pcl gen|check <file.pcl>`：纯编译直通（spawn 捕获 stdout）；
 *   - `/pcl version`：版本直通（协议握手，R16）；
 *   - 未知/缺省子命令 → 用法提示（不列 pass）；
 * - `pcl_write` / `pcl_read` 工具：写回通道（名单先行拒绝、引导当轮重试；
 *   参数经命名键 values 承载——pi@0.85.1 实测顶层开放形状被校验层剥空）
 *   与读取通道（查快照本地应答）；
 * - `before_agent_start`：仅当 read/write 名字存在时注入使用协议
 *   （systemPrompt 链式追加，不落会话）。
 *
 * 嵌入协议代理（§8.5 表，协议零新增、端点反转）＋上下文接续（§8.6）：
 * - 桥接状态上移**扩展模块级**（Bridge 单例，F1/F5：跨会话替换存活、管道随
 *   进程存活）；扩展实例退化为“注册点 + 事件泵”；
 * - 绑定 = 会话能力束两级（L2 完整 = 命令 ctx / ReplacedSessionContext；
 *   L1 受限 = 事件 ctx：sendUserMessage/abort/sessionManager 有、会话控制无）；
 *   任何 `/pcl` 子命令执行时以该命令 ctx 升级回 L2（含 /pcl version）；
 * - 三条接管规则：session_shutdown（quit→dispose 先关 stdin；reload→broken
 *   孤儿路径；new/resume/fork 非桥发起→awaitingAdoption）、session_start
 *   （awaitingAdoption 且子进程活→adopt L1，auto-follow）、/pcl 命令（adopt L2）；
 * - `:new`/`:load` 经 L2 绑定执行会话替换（withSession→新绑定，F3 可链式）；
 *   `:load` 预检：同文件 no-op、跨 cwd → embed-cross-cwd（A522）、
 *   打开失败 → success:false（→ R430）；
 * - 孤儿路径：adoption 时限（10s）内无新实例接管 → 在途命令回
 *   embed-orphaned（A521）→ 先关 stdin（空闲 pcl 经 EOF 以 A503 呈现）→
 *   宽限后 SIGTERM；
 * - 单活动桥；串行规则（pcl 上下文操作等响应后才发下一命令；命令泵顺序处理）；
 * - 提交期失败可见性：pi.sendUserMessage 发后即忘、错误经 <runtime>
 *   extension_error 流出（扩展不可订阅）——以 agent_start 存活检测兜底
 *   （15s 未见启动即合成 command:pcl 错误事件 → pcl A501）。
 *
 * 安装：复制/链接本文件到 ~/.pi/agent/extensions/（或其子目录），
 * 或由 pcl 经 `--connector-path` 直指本源文件（pi 经 jiti 直接加载 TS）。
 * 连接器仅 /pcl run 族需要宿主侧存在 pcl 可执行（PATH 解析，PCL_BIN 覆盖）。
 */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

// ---- pass 登记（机器子命令 + 工具共享） ---------------------------------

interface PassState {
  writable: string[];
  reads: Record<string, unknown>;
}

let current: PassState | null = null;
/** 模块级单活动桥（§8.6 总则 1/3；F1：跨会话替换存活）。 */
let moduleBridge: Bridge | null = null;
/** 工厂每次执行刷新（auto-follow 后的最新 API 绑定，F4）。 */
let latestPi: ExtensionAPI | null = null;
/** 最近事件 ctx（ExtensionAPI 无 ui，经此呈现接续提示）。 */
let latestEventCtx: any = null;

const PASS_PREFIX = "/pcl pass ";
const ADOPTION_TIMEOUT_MS = 10_000;   // 接续窗口（§8.6）
const NO_START_GRACE_MS = 15_000;     // 提交后未观测到 agent_start 的失败判定窗

function toolText(text: string) {
  return { content: [{ type: "text" as const, text }], details: {} };
}

function passError(message: string): never {
  throw new Error(message);
}

function registerPass(payload: any): string {
  if (typeof payload !== "object" || payload === null || typeof payload.text !== "string") {
    passError("pcl pass payload 缺少 text（应为 {writable, reads, text}）");
  }
  current = {
    writable: Array.isArray(payload.writable) ? payload.writable : [],
    reads: (payload.reads && typeof payload.reads === "object") ? payload.reads : {},
  };
  return payload.text;
}

/** 机器子命令：登记白名单/快照 + 提交文本（§8.2/§9.1）。 */
async function submitPass(payloadRaw: string, pi: ExtensionAPI): Promise<void> {
  let payload: any;
  try {
    payload = JSON.parse(payloadRaw);
  } catch (e) {
    passError(`pcl pass payload 非法 JSON：${e instanceof Error ? e.message : String(e)}`);
  }
  const text = registerPass(payload);
  // 缺省不展开：/ 开头文本原样入会话（信令与文本结构性分离，§8.2）
  pi.sendUserMessage(text);
}

function assistantText(msg: any): string {
  if (typeof msg?.content === "string") return msg.content;
  if (!Array.isArray(msg?.content)) return "";
  return msg.content
    .filter((b: any) => b?.type === "text" && typeof b.text === "string")
    .map((b: any) => b.text)
    .join("");
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---- 嵌入桥（模块级状态 + 绑定分级 + 接管规则，§8.6） ------------------------

type BindLevel = 1 | 2;

interface Binding {
  ctx: any;                 // ExtensionCommandContext | ReplacedSessionContext（L2）/ 事件 ctx（L1）
  level: BindLevel;
}

type BridgeState = "active" | "switching" | "awaitingAdoption" | "broken";

class Bridge {
  private proc: ChildProcess;
  private replyCache = "";
  private inPass = false;
  private agentStarted = false;
  private stderrTail: string[] = [];
  private startedAt = 0;
  private state: BridgeState = "active";
  private binding: Binding | null = null;
  private adoptionDeadline = 0;
  private orphanHandled = false;
  private disposed = false;
  private ticker: ReturnType<typeof setInterval>;
  done: Promise<number | null>;

  constructor(proc: ChildProcess, binding: Binding) {
    this.proc = proc;
    this.binding = binding;
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
      clearInterval(this.ticker);
      if (moduleBridge === this) moduleBridge = null;
      resolveExit(code);
    });
    this.ticker = setInterval(() => this.tick(), 1000);
  }

  stderr(): string {
    return this.stderrTail.join("").split(/\r?\n/).slice(-15).join("\n");
  }

  // ---- 绑定与接管 -----------------------------------------------------

  /** 绑定升级/接管（session_start → L1；withSession / /pcl 命令 → L2）。 */
  adopt(ctxLike: any, level: BindLevel, why = ""): void {
    if (this.disposed) return;
    const wasWaiting = this.state === "awaitingAdoption";
    this.binding = { ctx: ctxLike, level };
    this.state = "active";
    if (wasWaiting) {
      // ExtensionAPI 无 ui——经最近事件 ctx 呈现（尽力而为）
      try {
        latestEventCtx?.ui?.setStatus?.("pcl", "pcl 嵌入运行已随会话切换接续");
      } catch { /* 尽力 */ }
      void why;
    }
  }

  /** 最近可用的 ui（绑定 ctx 优先——替换后旧命令 ctx 已过期）。 */
  ui(): any | null {
    return this.binding?.ctx?.ui ?? latestEventCtx?.ui ?? null;
  }

  /** session_shutdown（§8.6 接管规则表）。 */
  onSessionShutdown(reason: string): void {
    if (this.disposed) return;
    if (this.state === "switching") return;   // 桥发起的替换：序列自管
    this.adoptionDeadline = Date.now() + ADOPTION_TIMEOUT_MS;
    if (reason === "quit") {
      // 先关 stdin：pcl 读线程 EOF → A503（宽限后 SIGTERM 兜底）
      this.state = "broken";
      this.dispose();
    } else if (reason === "reload") {
      this.state = "broken";                  // 模块即将重载（F1 例外）→ 孤儿路径
      try {
        latestEventCtx?.ui?.notify?.("reload 将中断进行中的 /pcl run", "warning");
      } catch { /* 尽力 */ }
    } else {
      // new / resume / fork 且非桥发起 → 等待新实例接管（auto-follow）
      this.state = "awaitingAdoption";
    }
  }

  /** session_start：awaitingAdoption 且子进程活 → adopt L1（auto-follow）。 */
  onSessionStart(ctxLike: any): void {
    if (this.disposed || this.state !== "awaitingAdoption") return;
    if (this.proc.exitCode !== null) return;
    this.adopt(ctxLike, 1, "session_start");
  }

  /** 等待可用绑定（awaitingAdoption/switching 阻塞；超时 → null = 孤儿）。 */
  private async ensureBinding(): Promise<Binding | null> {
    while (!this.disposed) {
      if (this.state === "active" && this.binding) return this.binding;
      if ((this.state === "awaitingAdoption" || this.state === "broken")
          && Date.now() >= this.adoptionDeadline) {
        return null;
      }
      await sleep(100);
    }
    return null;
  }

  // ---- 事件泵（全局订阅喂入；F7：只有当前会话实例收到事件） ------------------

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
    if (ev.type === "agent_start") {
      this.agentStarted = true;
      return;
    }
    this.write(ev);   // tool_execution_start 等：原样转发
  }

  private write(obj: any): void {
    if (this.proc.stdin && !this.proc.stdin.destroyed) {
      try {
        this.proc.stdin.write(JSON.stringify(obj) + "\n");
      } catch { /* EPIPE：子进程将退出 */ }
    }
  }

  // ---- 命令泵（§8.5 代理表 + §8.6 上下文接续） ------------------------------

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
      return;
    }
    const id = cmd.id;
    const respond = (resp: any) => this.write(resp);

    // 孤儿/待接管：先等绑定（超时 → embed-orphaned，§8.6）
    if (this.state !== "active" && cmd.type !== "abort") {
      const deadlineHit = await this.ensureBinding();
      if (!deadlineHit) {
        respond(this.fail(id, cmd.type, "接续窗口内无新实例接管（孤儿路径）",
          { reason: "embed-orphaned" }));
        return;
      }
    }

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
        const text = registerPass(payload);
        this.replyCache = "";
        this.inPass = true;
        this.agentStarted = false;
        this.startedAt = Date.now();
        try {
          latestPi!.sendUserMessage(text);   // 模块级 API（F4；随替换重绑）
        } catch (err) {
          this.write({
            type: "extension_error", extensionPath: "command:pcl", event: "command",
            error: `sendUserMessage 抛错：${err instanceof Error ? err.message : String(err)}`,
          });
        }
        respond(this.ok(id, "prompt"));
        return;
      }
      case "get_state": {
        const b = await this.ensureBinding();
        if (!b) { respond(this.fail(id, "get_state", "无可用绑定")); return; }
        const sessionFile = b.ctx.sessionManager?.getSessionFile?.() ?? null;
        respond(this.ok(id, "get_state", { sessionFile }));
        return;
      }
      case "get_commands": {
        const commands = (latestPi?.getCommands() ?? []).map((c: any) => ({
          name: c.name, source: c.source,
        }));
        respond(this.ok(id, "get_commands", { commands }));
        return;
      }
      case "set_session_name": {
        // embed 下 pcl 不发（不重命名宿主会话，§8.3）；映射保留兼容
        try {
          latestPi!.setSessionName(String(cmd.name ?? ""));
          respond(this.ok(id, "set_session_name"));
        } catch (err) {
          respond(this.fail(id, "set_session_name",
            err instanceof Error ? err.message : String(err)));
        }
        return;
      }
      case "new_session":
      case "switch_session": {
        await this.contextOp(cmd, respond);
        return;
      }
      case "context": {
        // 上下文注入 $(@ … @)：sendMessage triggerTurn=false——进入 LLM
        // 上下文但不触发推理（下一 prompt 时投递）
        try {
          latestPi!.sendMessage({
            customType: "pcl-context",
            content: String(cmd.text ?? ""),
            display: false,
          }, { triggerTurn: false, deliverAs: "nextTurn" });
          respond(this.ok(id, "context"));
        } catch (err) {
          respond(this.fail(id, "context",
            err instanceof Error ? err.message : String(err)));
        }
        return;
      }
      case "note": {
        // 模板注记 $(# …)：附加进会话流（custom entry，不进 LLM 上下文）
        try {
          latestPi!.appendEntry("pcl-note", { text: String(cmd.text ?? "") });
          respond(this.ok(id, "note"));
        } catch (err) {
          respond(this.fail(id, "note",
            err instanceof Error ? err.message : String(err)));
        }
        return;
      }
      case "get_last_assistant_text": {
        respond(this.ok(id, "get_last_assistant_text",
          { text: this.replyCache || null }));
        return;
      }
      case "abort": {
        try {
          const b = this.binding;
          b?.ctx.abort?.();
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

  /** :new / :load——会话替换经 L2 绑定执行，withSession 刷新绑定（F3 可链式）。 */
  private async contextOp(cmd: any, respond: (r: any) => void): Promise<void> {
    const b = await this.ensureBinding();
    if (!b) {
      respond(this.fail(cmd.id, cmd.type, "无可用绑定",
        { reason: "embed-orphaned" }));
      return;
    }
    if (b.level < 2) {
      // auto-follow 后的 L1 绑定收到上下文操作 → A523（§8.6）
      respond(this.fail(cmd.id, cmd.type,
        "会话切换后绑定降级（L1）：执行任一 /pcl 命令恢复，或改用正向 CLI",
        { reason: "embed-no-session-control" }));
      return;
    }
    if (cmd.type === "switch_session") {
      const token = String(cmd.sessionPath ?? "");
      const cwd = b.ctx.cwd ?? process.cwd();
      const currentFile = b.ctx.sessionManager?.getSessionFile?.();
      if (token === currentFile) {
        respond(this.ok(cmd.id, "switch_session", { cancelled: false }));   // no-op
        return;
      }
      let targetCwd: string | undefined;
      try {
        targetCwd = SessionManager.open(token).getCwd() || undefined;
      } catch {
        respond(this.fail(cmd.id, "switch_session", `无法打开目标会话：${token}`));
        return;   // pcl → R430
      }
      if (!targetCwd || targetCwd !== cwd) {
        // 跨 cwd：模块必重载、桥必孤儿——明确引导走正向 CLI（§8.6）
        respond(this.fail(cmd.id, "switch_session",
          `:load 目标 cwd（${targetCwd ?? "未知"}）≠ 当前（${cwd}），请改用正向 CLI`,
          { reason: "embed-cross-cwd" }));
        return;
      }
      await this.replace(b, (withSession) =>
        b.ctx.switchSession(token, { withSession }), respond, cmd);
      return;
    }
    await this.replace(b, (withSession) =>
      b.ctx.newSession({ withSession }), respond, cmd);
  }

  private async replace(
    b: Binding,
    call: (withSession: (ctx2: any) => void) => Promise<any>,
    respond: (r: any) => void,
    cmd: any,
  ): Promise<void> {
    this.state = "switching";
    try {
      const result = await call((ctx2: any) => {
        // withSession：新会话上下文（ReplacedSessionContext，L2，可链式）
        this.adopt(ctx2, 2, "withSession");
      });
      if (result?.cancelled) {
        // 被他扩展取消：无替换发生，旧绑定仍有效（§8.6 取消语义）
        this.state = "active";
        respond(this.ok(cmd.id, cmd.type, { cancelled: true }));
        return;
      }
      respond(this.ok(cmd.id, cmd.type, { cancelled: false }));
    } catch (err) {
      this.state = "active";
      respond(this.fail(cmd.id, cmd.type,
        err instanceof Error ? err.message : String(err)));
    }
  }

  // ---- 孤儿与生命周期 ---------------------------------------------------

  /** 每秒巡检：pass 存活检测 + 孤儿路径（§8.6）。 */
  private tick(): void {
    // 提交期失败检测（agent_start 存活观测）
    if (this.inPass && !this.agentStarted
        && Date.now() - this.startedAt >= NO_START_GRACE_MS) {
      this.inPass = false;
      this.write({
        type: "extension_error", extensionPath: "command:pcl", event: "command",
        error: "pass 提交后未见 agent 启动（无模型/鉴权失败/宿主拒绝？）",
      });
    }
    // 孤儿：adoption 时限到期且无接管——在途命令经 ensureBinding 逐条回
    // embed-orphaned（A521）；随后先关 stdin（空闲 pcl 经 EOF 以 A503 呈现）、
    // 宽限后 SIGTERM
    if (!this.orphanHandled
        && (this.state === "awaitingAdoption" || this.state === "broken")
        && Date.now() >= this.adoptionDeadline) {
      this.orphanHandled = true;
      this.dispose();
    }
  }

  dispose(killAfterMs = 3000): void {
    if (this.disposed) return;
    this.disposed = true;
    try { this.proc.stdin?.end(); } catch { /* 已断 */ }
    const t = setTimeout(() => {
      try { this.proc.kill("SIGTERM"); } catch { /* 已退出 */ }
    }, killAfterMs);
    t.unref?.();
  }
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

/** 入会话流的最大行数（超出截断；完整内容看输出文件）。 */
const ENTRY_MAX_LINES = 800;
/** 未展开时的预览行数（展开键查看全部）。 */
const ENTRY_PREVIEW_LINES = 15;

/**
 * 把结果以 custom entry 附加进会话流：不进 LLM 上下文、随对话滚动（无常驻
 * widget）、随会话持久；TUI 经 registerEntryRenderer 渲染（未展开时预览 +
 * 截断，展开看全部；RPC/嵌入宿主无渲染也不影响持久化）。
 */
function appendResult(pi: ExtensionAPI, title: string, lines: string[],
                      path?: string) {
  const capped = lines.length > ENTRY_MAX_LINES
    ? [...lines.slice(0, ENTRY_MAX_LINES),
       `…（共 ${lines.length} 行，已截断；完整内容见输出文件）`]
    : lines;
  try {
    pi.appendEntry("pcl-run-output", { title, lines: capped, path });
  } catch { /* 尽力：呈现失败不影响退出码上报 */ }
}

async function runEmbedded(ctx: ExtensionCommandContext, tokens: string[]): Promise<void> {
  const parsed = parseRunArgs(tokens);
  if ("error" in parsed) {
    ctx.ui.notify(`pcl run：${parsed.error}`, "error");
    return;
  }
  const { file, prompt, opts } = parsed;
  if (moduleBridge) {
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
  const bridge = new Bridge(proc, { ctx, level: 2 });
  moduleBridge = bridge;
  try {
    const code = await bridge.done;
    const output = safeRead(outPath);
    // 运行中可能发生会话替换（:new/:load）：呈现用最新绑定（旧 ctx 已过期）
    const ui = bridge.ui() ?? ctx.ui;
    if (code === 0) {
      ui.notify?.(`pcl run 完成（退出码 0）· 输出：${outPath}`, "info");
    } else {
      const tail = bridge.stderr().trim().split("\n").slice(-5).join(" | ");
      ui.notify?.(`pcl run 失败（退出码 ${code ?? "?"}）· ${tail}`, "error");
    }
  } finally {
    if (moduleBridge === bridge) moduleBridge = null;
    const ui = bridge.ui() ?? ctx.ui;
    try { ui.setStatus?.("pcl", undefined); } catch { /* 尽力 */ }
    // tmp 输出文件保留（会话流尾注已给出路径；系统 tmp 自行回收）
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

async function passthrough(pi: ExtensionAPI, ctx: ExtensionCommandContext,
                            tokens: string[]): Promise<void> {
  const { code, out, err } = await spawnCapture(tokens);
  const lines = [
    ...out.split("\n"),
    ...(err.trim() ? ["--- stderr 尾部 ---",
                     ...err.trim().split("\n").slice(-15)] : []),
  ];
  if (tokens[0] === "version") {
    ctx.ui.notify(out.trim() || `pcl version（退出码 ${code ?? "?"}）`, "info");
    return;
  }
  appendResult(pi, `pcl ${tokens[0]}（退出码 ${code ?? "?"}）`, lines);
  ctx.ui.notify(`pcl ${tokens[0]} ${code === 0 ? "完成" : `失败（退出码 ${code ?? "?"}）`}`,
                code === 0 ? "info" : "error");
}

function usage(ctx: ExtensionCommandContext): void {
  ctx.ui.notify([
    "PCL 用法：",
    "  /pcl run <file.pcl> [PROMPT…] [选项]   在当前会话执行 PCL",
    "  /pcl gen|check <file.pcl>              生成源 / 编译检查",
    "  /pcl config [file]                     打印生效设置及来源",
    "  /pcl version                           版本",
    "  选项透传 pcl CLI（--var/--timeout/--trace/--cache/-o 等）；",
    "  正向专属选项（--agent/--pi-bin/--connector-path/--pi-arg/--script）被拒。",
  ].join("\n"), "info");
}

// ---- ~/.pcl/bin/ 自动命令注册 ------------------------------------------------

function registerBinCommands(pi: ExtensionAPI): void {
  const binDir = join(homedir(), ".pcl", "bin");
  if (!existsSync(binDir)) return;

  function isExecutable(p: string): boolean {
    try {
      return (statSync(p).mode & 0o111) !== 0;
    } catch {
      return false;
    }
  }

  function scan(dir: string, prefix: string): void {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = join(dir, e.name);
      if (e.isDirectory()) {
        scan(full, prefix + e.name + "-");
      } else if (e.isFile() && isExecutable(full)) {
        const cmdName = "pcl-" + prefix + e.name;
        const relPath = prefix + e.name;
        pi.registerCommand(cmdName, {
          description: `~/.pcl/bin/${relPath}`,
          handler: async (args: string, ctx: ExtensionCommandContext) => {
            const proc = spawn(full, args.trim().split(/\s+/).filter(Boolean), {
              stdio: ["ignore", "pipe", "pipe"],
            });
            let out = "", err = "";
            proc.stdout?.setEncoding("utf-8");
            proc.stdout?.on("data", (c: string) => (out += c));
            proc.stderr?.setEncoding("utf-8");
            proc.stderr?.on("data", (c: string) => (err += c));
            const code = await new Promise<number | null>((res) => {
              proc.on("close", (c) => res(c));
              proc.on("error", () => res(null));
            });
            const text = (code === 0 ? out : out + (err ? "\n" + err : "")).trim();
            if (text) {
              appendResult(pi, `${cmdName}（退出码 ${code ?? "?"}）`,
                           text.split("\n"));
            }
            ctx.ui.notify(`${cmdName} ${code === 0 ? "完成" : `失败（${code ?? "?"}）`}`,
                          code === 0 ? "info" : "error");
          },
        });
      }
    }
  }
  scan(binDir, "");
}

// ---- 扩展入口 ---------------------------------------------------------------

export default function (pi: ExtensionAPI): void {
  latestPi = pi;

  // /pcl run 结果的会话流渲染（custom entry：不进 LLM 上下文；未展开预览，
  // 展开键查看全部——替代旧常驻 widget）
  // 模板注记 $(# …)：随对话滚动、不进上下文（嵌入形态的渲染目的地）
  pi.registerEntryRenderer("pcl-note", (entry: any) => {
    const text = String(entry?.data?.text ?? "");
    return new Text(`▌ ${text}`, 1, 0);
  });

  registerBinCommands(pi);

  pi.registerEntryRenderer("pcl-run-output", (entry: any, options: any) => {
    const d = entry?.data ?? {};
    const lines: string[] = Array.isArray(d.lines) ? d.lines : [];
    const shown = options?.expanded ? lines : lines.slice(0, ENTRY_PREVIEW_LINES);
    const body = [
      ...(d.title ? [`── ${d.title} ──`] : []),
      ...shown,
      ...(!options?.expanded && lines.length > ENTRY_PREVIEW_LINES
        ? [`…（共 ${lines.length} 行，展开查看全部）`] : []),
      ...(d.path ? [`完整输出：${d.path}`] : []),
    ].join("\n");
    return new Text(body, 1, 0);
  });

  pi.registerCommand("pcl", {
    description: "PCL：/pcl run <file.pcl> [PROMPT] — 在当前会话执行 PCL（与 pcl CLI 对齐）",
    getArgumentCompletions: (prefix: string) => {
      const subs = ["run", "gen", "check", "config", "version"]
        .map((s) => ({ value: s, label: s }))
        .filter((i) => i.value.startsWith(prefix));
      return subs.length ? subs : null;
    },
    handler: async (args: string, ctx) => {
      const trimmed = args.trim();
      const sub = trimmed.split(/\s+/)[0] ?? "";
      // 能力恢复入口：任何 /pcl 子命令以当前命令 ctx 升级绑定回 L2（§8.6）
      moduleBridge?.adopt(ctx, 2, "/pcl 命令");
      if (sub === "pass") {
        return submitPass(trimmed.slice(4).trim(), pi);
      }
      if (sub === "run") {
        return runEmbedded(ctx, trimmed.split(/\s+/).slice(1));
      }
      if (sub === "gen" || sub === "check" || sub === "config" || sub === "version") {
        return passthrough(pi, ctx, trimmed.split(/\s+/));
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

  // 事件泵（F7：只有当前会话实例收到事件；模块级桥跨替换存活）
  pi.on("agent_start", async () => {
    moduleBridge?.forwardEvent({ type: "agent_start" });
  });
  pi.on("agent_settled", async () => {
    current = null;   // pass 边界：清登记（后续轮次不再暴露读写工具协议）
    moduleBridge?.forwardEvent({ type: "agent_settled" });
  });
  pi.on("tool_execution_start", async (event) => {
    moduleBridge?.forwardEvent({
      type: "tool_execution_start",
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      args: event.args,
    });
  });
  pi.on("message_update", async (event) => {
    moduleBridge?.forwardEvent(event);
  });
  pi.on("message_end", async (event) => {
    moduleBridge?.forwardEvent(event);
  });
  pi.on("turn_end", async (event) => {
    moduleBridge?.forwardEvent(event);
  });

  // ---- 接管规则（§8.6） --------------------------------------------------
  pi.on("session_start", async (_event, ctx) => {
    latestEventCtx = ctx;
    moduleBridge?.onSessionStart(ctx);
  });
  pi.on("session_shutdown", async (event) => {
    moduleBridge?.onSessionShutdown(String(event.reason ?? ""));
  });
}
