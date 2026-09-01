import { useEffect, useState } from "react";
import type { DisplayMessage } from "@/store/chat";
import { extractRefTags, stripRefTags } from "@/utils/fileTags";
import { api } from "@/api/client";
import MarkdownRenderer from "./MarkdownRenderer";
import "./MessageItem.css";

interface Props {
  message: DisplayMessage;
  isPaused: boolean;
  // 是否为最后一张 assistant 卡片（重新生成按钮仅出现在这里）
  isLastAssistant?: boolean;
  // 是否允许重新生成（run 进行中禁用）
  canRegenerate?: boolean;
  onRegenerate?: () => void;
  // TTS 模型已加载时显示朗读按钮
  ttsLoaded?: boolean;
}

/** 从 metadata.forced_refs 中查找引用的显示名 */
function findRefName(
  metadata: Record<string, unknown> | undefined,
  kind: string,
  id: string,
): string | undefined {
  const refs = metadata?.forced_refs;
  if (!Array.isArray(refs)) return undefined;
  for (const r of refs) {
    if (
      r &&
      typeof r === "object" &&
      (r as Record<string, unknown>).type === kind.toLowerCase() &&
      String((r as Record<string, unknown>).id) === id
    ) {
      const name = (r as Record<string, unknown>).file_name ?? (r as Record<string, unknown>).name;
      return typeof name === "string" ? name : undefined;
    }
  }
  return undefined;
}

function FileTagCard({ name, fileId }: { name: string; fileId: string }) {
  return (
    <div className="file-attachment-card" title={`file_id: ${fileId}`}>
      <div className="file-attachment-icon">📎</div>
      <div className="file-attachment-info">
        <div className="file-attachment-name">{name}</div>
        <div className="file-attachment-meta">
          <span>已上传 · 发送时自动注入</span>
        </div>
      </div>
    </div>
  );
}

// ===== 旧「/」强制引用标记解析（兼容 /skill:id、/cli:name 输入语法）=====

const SLASH_REF_RE = /(?:^|\s)\/(skill|cli):([A-Za-z0-9_\-]+)/g;

interface SlashRefInfo {
  kind: "skill" | "cli";
  id: string;
}

/** 从用户文本中提取 /skill:id、/cli:name 标记并剥离，返回引用列表与剩余文本 */
function splitSlashRefs(text: string): { refs: SlashRefInfo[]; text: string } {
  const refs: SlashRefInfo[] = [];
  const seen = new Set<string>();
  SLASH_REF_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = SLASH_REF_RE.exec(text)) !== null) {
    const key = `${m[1]}:${m[2]}`;
    if (!seen.has(key)) {
      seen.add(key);
      refs.push({ kind: m[1] as SlashRefInfo["kind"], id: m[2] });
    }
  }
  if (refs.length === 0) return { refs, text };
  const stripped = text
    .replace(SLASH_REF_RE, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
  return { refs, text: stripped };
}

// skill id → 名称的模块级缓存：多条消息共享一次请求
let slashSkillNameCache: Record<string, string> | null = null;
let slashSkillNamePromise: Promise<Record<string, string>> | null = null;

function loadSkillNames(): Promise<Record<string, string>> {
  if (slashSkillNameCache) return Promise.resolve(slashSkillNameCache);
  if (!slashSkillNamePromise) {
    slashSkillNamePromise = api
      .listSkills()
      .then((skills) => {
        slashSkillNameCache = {};
        for (const s of skills) slashSkillNameCache[s.id] = s.name || s.id;
        return slashSkillNameCache;
      })
      .catch(() => {
        slashSkillNamePromise = null;
        return {};
      });
  }
  return slashSkillNamePromise;
}

/** 强制引用 chip 列表：Skill 显示名称（异步解析），CLI 显示名称本身 */
function SlashRefChipList({ refs }: { refs: SlashRefInfo[] }) {
  const [names, setNames] = useState<Record<string, string>>(
    slashSkillNameCache ?? {},
  );
  useEffect(() => {
    let cancelled = false;
    loadSkillNames().then((map) => {
      if (!cancelled) setNames(map);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="attachments-block">
      {refs.map((r) => {
        const label = r.kind === "skill" ? names[r.id] || r.id : r.id;
        return (
          <div
            key={`${r.kind}:${r.id}`}
            className={`slash-ref-chip ${r.kind}`}
            title={`${r.kind === "skill" ? "Skill" : "CLI"}：${label}`}
          >
            <svg className="slash-ref-icon" viewBox="0 0 16 16" aria-hidden="true">
              {r.kind === "skill" ? (
                <path d="M9 1 3 9h4l-1 6 6-8H8l1-6z" />
              ) : (
                <>
                  <rect x="2" y="2" width="12" height="12" rx="2" />
                  <path d="M5.5 6l5 5M10.5 6l-5 5" />
                </>
              )}
            </svg>
            <span>{label}</span>
          </div>
        );
      })}
    </div>
  );
}

/** 用户消息卡片：<Skill/File/Cli:id/> 占位符渲染为引用 chip / 文件卡片 */
function UserMessage({ message }: { message: DisplayMessage }) {
  const tagRefs = extractRefTags(message.content);
  const fileRefs = tagRefs.filter((r) => r.kind === "File");
  const otherRefs = tagRefs.filter((r) => r.kind !== "File");
  const { refs: slashRefs, text: noSlashText } = splitSlashRefs(message.content);
  const cleanText = stripRefTags(noSlashText);
  const metadata = message.metadata;

  return (
    <div className="message-item user">
      <div className="message-bubble user-bubble">
        {fileRefs.length > 0 && (
          <div className="attachments-block">
            {fileRefs.map((r) => (
              <FileTagCard
                key={r.id}
                name={findRefName(metadata, "File", r.id) ?? r.id}
                fileId={r.id}
              />
            ))}
          </div>
        )}
        {(otherRefs.length > 0 || slashRefs.length > 0) && (
          <SlashRefChipList
            refs={[
              ...otherRefs.map((r) => ({
                kind: r.kind.toLowerCase() as "skill" | "cli",
                id: findRefName(metadata, r.kind, r.id) ?? r.id,
              })),
              ...slashRefs,
            ]}
          />
        )}
        <div className="message-content">{cleanText}</div>
      </div>
    </div>
  );
}

function ToolResultCard({ message }: { message: DisplayMessage }) {
  const [expanded, setExpanded] = useState(false);
  const kind = message.toolResultKind || "tool";
  const summaryText = message.content
    ? `${message.content.slice(0, 80)}${message.content.length > 80 ? "..." : ""}`
    : "(无内容)";

  return (
    <div className="message-item tool">
      <div className="message-bubble tool-bubble">
        <button
          type="button"
          className="tool-summary"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          <span className="tool-kind">{kind}</span>
          <span className="tool-summary-text">{summaryText}</span>
          <span className="tool-toggle">{expanded ? "收起" : "展开"}</span>
        </button>
        {expanded && <pre className="tool-result">{message.content}</pre>}
      </div>
    </div>
  );
}

/** 剥离 Markdown 语法，生成适合朗读的纯文本 */
function stripMarkdownForTts(md: string): string {
  return md
    // 代码块跳过朗读
    .replace(/```[\s\S]*?```/g, " ")
    // 行内代码保留内容
    .replace(/`([^`]+)`/g, "$1")
    // 图片跳过
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    // 链接只保留文字
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    // 标题 / 引用 / 列表标记
    .replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, "")
    .replace(/^([ \t]*)>[ \t]?/gm, "$1")
    .replace(/^([ \t]*)[-*+][ \t]+/gm, "$1")
    // 强调 / 删除线
    .replace(/(\*\*|__|\*|_|~~)/g, "")
    // 引用占位符标签
    .replace(/<(Skill|File|Cli):[^>]+>/g, " ")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

/** 复制文本：优先 Clipboard API，失败时回退 execCommand（Tauri WebView 兼容） */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

function IconCopy() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <rect x="5" y="5" width="9" height="9" rx="1.5" />
      <path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5" />
    </svg>
  );
}

function IconRegenerate() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
      <path d="M13.7 1.8v2.9h-2.9" />
    </svg>
  );
}

function IconSpeak() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 2.5 4.5 5.5H2v5h2.5L8 13.5v-11z" />
      <path d="M10.5 5.5a3.5 3.5 0 0 1 0 5" />
      <path d="M12.3 3.7a6 6 0 0 1 0 8.6" />
    </svg>
  );
}

/** assistant 消息卡片底部操作条：左下 token 用量，右下 复制/重新生成/朗读 */
function AssistantFooter({
  message,
  isLastAssistant,
  canRegenerate,
  onRegenerate,
  ttsLoaded,
}: {
  message: DisplayMessage;
  isLastAssistant?: boolean;
  canRegenerate?: boolean;
  onRegenerate?: () => void;
  ttsLoaded?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  const usage = message.tokenUsage;
  const usageText =
    usage && typeof usage.total_tokens === "number"
      ? `输入 ${usage.prompt_tokens ?? 0} · 输出 ${usage.completion_tokens ?? 0} · 共 ${usage.total_tokens} tokens`
      : null;

  async function handleCopy() {
    const ok = await copyText(message.content);
    if (ok) setCopied(true);
  }

  async function handleSpeak() {
    const text = stripMarkdownForTts(message.content);
    if (!text) return;
    setSpeaking(true);
    try {
      await api.ttsSpeak({ text });
    } catch (err) {
      console.error("[MessageItem] 朗读失败:", err);
      setSpeaking(false);
      return;
    }
    // 后台异步播放无法得知结束时刻，短暂高亮后恢复
    setTimeout(() => setSpeaking(false), 2000);
  }

  return (
    <div className="message-footer">
      <div className="token-usage">{usageText ?? "\u00A0"}</div>
      <div className="message-actions">
        <button
          type="button"
          className="msg-action-btn"
          onClick={handleCopy}
          title="复制原文"
        >
          <IconCopy />
          <span>{copied ? "已复制" : "复制"}</span>
        </button>
        {isLastAssistant && canRegenerate && onRegenerate && (
          <button
            type="button"
            className="msg-action-btn"
            onClick={onRegenerate}
            title="清空本轮推理并重新生成"
          >
            <IconRegenerate />
            <span>重新生成</span>
          </button>
        )}
        {ttsLoaded && (
          <button
            type="button"
            className={`msg-action-btn${speaking ? " active" : ""}`}
            onClick={handleSpeak}
            title="朗读本条消息"
          >
            <IconSpeak />
            <span>{speaking ? "朗读中" : "朗读"}</span>
          </button>
        )}
      </div>
    </div>
  );
}

function AssistantMessage({
  message,
  isPaused,
  isLastAssistant,
  canRegenerate,
  onRegenerate,
  ttsLoaded,
}: Props) {
  const isStreaming = message.isStreaming;
  const showCursor = isStreaming && !isPaused;

  return (
    <div className="message-item assistant">
      <div className="message-bubble assistant-bubble">
        {message.thinking && (
          <details className="thinking-block" open={isStreaming && !message.content}>
            <summary>思考过程</summary>
            <div className="thinking-content">{message.thinking}</div>
          </details>
        )}

        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="tool-calls">
            {message.toolCalls.map((tc, i) => (
              <details key={i} className="tool-call-block">
                <summary>
                  {tc.raw ? `工具调用：${tc.raw.slice(0, 80)}${tc.raw.length > 80 ? "..." : ""}` : "工具调用"}
                  {tc.done && <span className="tool-done"> ✓</span>}
                </summary>
                {tc.raw && <pre className="tool-raw">{tc.raw}</pre>}
                {tc.result != null && (
                  <pre className="tool-result">
                    {typeof tc.result === "string"
                      ? tc.result
                      : JSON.stringify(tc.result, null, 2)}
                  </pre>
                )}
              </details>
            ))}
          </div>
        )}

        {message.content && (
          <div className="message-content">
            <MarkdownRenderer content={message.content} />
            {showCursor && <span className="typing-cursor">▋</span>}
          </div>
        )}

        {!message.content && !message.thinking && (!message.toolCalls || message.toolCalls.length === 0) && (
          <div className="message-content placeholder">
            {isStreaming ? "正在思考..." : "(空)"}
          </div>
        )}

        {message.aborted && (
          <div className="aborted-tag">运行中断，请重发</div>
        )}

        {!isStreaming && message.content && (
          <AssistantFooter
            message={message}
            isLastAssistant={isLastAssistant}
            canRegenerate={canRegenerate}
            onRegenerate={onRegenerate}
            ttsLoaded={ttsLoaded}
          />
        )}
      </div>
    </div>
  );
}

export default function MessageItem(props: Props) {
  const { message } = props;

  if (message.role === "user") {
    return <UserMessage message={message} />;
  }

  if (message.role === "tool") {
    return <ToolResultCard message={message} />;
  }

  return <AssistantMessage {...props} />;
}
