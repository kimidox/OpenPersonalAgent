import { useEffect, useState } from "react";
import type { DisplayMessage } from "@/store/chat";
import { extractRefTags, stripRefTags } from "@/utils/fileTags";
import { api } from "@/api/client";
import MarkdownRenderer from "./MarkdownRenderer";
import "./MessageItem.css";

interface Props {
  message: DisplayMessage;
  isPaused: boolean;
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

export default function MessageItem({ message, isPaused }: Props) {
  if (message.role === "user") {
    return <UserMessage message={message} />;
  }

  if (message.role === "tool") {
    return <ToolResultCard message={message} />;
  }

  // assistant
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
      </div>
    </div>
  );
}
