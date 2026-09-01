/**
 * 全局 chat store：会话列表 / 当前会话 / 消息历史。
 *
 * 使用 Zustand，避免 prop drilling。
 * - 会话列表从 REST 拉取
 * - 当前会话的消息历史：先从 REST 加载（getConversation.messages），
 *   再由 useStream 实时累加一条 pending assistant 消息
 */

import { create } from "zustand";
import { api, APIError } from "@/api/client";
import type {
  ConversationSummary,
  ConversationDetail,
} from "@/types/api";
import type { AwaitUserSpec } from "@/types/events";

export interface TokenUsageInfo {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface DisplayMessage {
  // 本地生成的唯一 id（用于 React key）
  localId: string;
  role: "user" | "assistant" | "system" | "tool";
  // 用户消息：可能含 <Skill:id/> / <File:fid/> / <Cli:name/> 占位符的完整 query
  // （渲染时由 MessageItem 解析剥离）；assistant 消息：分 thinking / content /
  // toolCalls 三段；tool 消息：工具结果文本
  content: string;
  // 消息元数据（来自后端 ext：forced_refs / files / type 等），引用 chip 渲染依据
  metadata?: Record<string, unknown>;
  thinking?: string;
  toolCalls?: { raw: string; result?: unknown; done: boolean }[];
  // tool 结果卡片的来源 kind（base_tool / tool）
  toolResultKind?: string;
  timestamp: number;
  // 该 assistant 消息是否仍在流式中（用于打字机渲染）
  isStreaming?: boolean;
  // 本轮 LLM 调用消耗的 token 数（token.usage 事件同步）
  tokenUsage?: TokenUsageInfo | null;
  // 是否因 sidecar 重启被中断
  aborted?: boolean;
  // 是否等待用户回复
  awaitingUser?: boolean;
  // ask_user 工具的 spec 数据（问题、选项、上下文）
  awaitUserSpec?: AwaitUserSpec | null;
}

interface ChatState {
  conversations: ConversationSummary[];
  currentConversationId: string | null;
  currentConversation: ConversationDetail | null;
  messages: DisplayMessage[];
  loadingConversations: boolean;
  loadingMessages: boolean;
  error: string | null;

  loadConversations: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  createConversation: () => Promise<string>;
  deleteConversation: (id: string) => Promise<void>;
  updateConversationTitle: (id: string, title: string) => Promise<void>;
  clearMessages: () => void;

  // 实时消息操作（由 useStream 调用）
  appendUserMessage: (content: string, metadata?: Record<string, unknown>) => void;
  startAssistantMessage: (runId: string) => void;
  // 开启下一轮 assistant 卡片（模型新一轮发言前调用）
  newAssistantMessage: () => void;
  updateAssistantMessage: (patch: Partial<DisplayMessage>) => void;
  // token 用量写入最后一张 assistant 卡片；token.usage 事件可能晚于
  // message.complete 到达（后端 finally 块推送），此时卡片已非流式，
  // 不能走 updateAssistantMessage（只匹配 isStreaming 卡片）
  applyTokenUsage: (usage: TokenUsageInfo) => void;
  completeAssistantMessage: () => void;
  // 追加一条独立的工具结果卡片；
  // insertBefore=true 时插到最后一张流式卡片之前（运行时确认续跑的
  // confirm 分支结果先于本 run 首个 turn.start 到达，需保持时间顺序）
  appendToolResultMessage: (content: string, kind?: string, insertBefore?: boolean) => void;
  // 清除所有消息的 awaitingUser 标记（用户回复 ask_user 后隐藏卡片）
  clearAwaitingUser: () => void;
  // 重新生成：删除最后一条 user 消息之后的所有卡片（上一轮推理结果）
  truncateLastTurn: () => void;
  setMessages: (msgs: DisplayMessage[]) => void;
}

let localIdCounter = 0;
const nextLocalId = () => `m${++localIdCounter}`;

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  currentConversation: null,
  messages: [],
  loadingConversations: false,
  loadingMessages: false,
  error: null,

  loadConversations: async () => {
    set({ loadingConversations: true, error: null });
    try {
      const conversations = await api.listConversations();
      set((s) => {
        // 后端可能用首条 query 更新了标题，同步当前会话的详情
        const cur = s.currentConversation;
        const refreshed = cur
          ? conversations.find((c) => c.conversation_id === cur.conversation_id)
          : undefined;
        return {
          conversations,
          loadingConversations: false,
          currentConversation:
            cur && refreshed ? { ...cur, title: refreshed.title } : cur,
        };
      });
    } catch (err) {
      const msg = err instanceof APIError ? err.message : String(err);
      set({ loadingConversations: false, error: `加载会话列表失败：${msg}` });
    }
  },

  selectConversation: async (id) => {
    set({ loadingMessages: true, currentConversationId: id, error: null });
    try {
      const detail = await api.getConversation(id);
      const displayMessages: DisplayMessage[] = [];
      // 暂存前一条 metadata.type==="think" 的独立消息内容
      // 后端保存：先保存一条 role=assistant + metadata.type=think 的独立消息，
      // 紧接着保存真正的 assistant 回复。加载时需要把 think 消息合并进下一条 assistant。
      let pendingThinking: string | null = null;

      for (const m of detail.messages) {
        const role = (m.role as "user" | "assistant" | "system" | "tool") ?? "assistant";
        const metadata = m.metadata ?? {};
        const metaType = metadata.type as string | undefined;
        const rawContent = m.content;
        const contentStr =
          typeof rawContent === "string" ? rawContent : JSON.stringify(rawContent);

        // 跳过仅用于保存 tool_calls 元数据、没有实际文本的 assistant 记录，
        // 避免历史加载后出现大量空 assistant 卡片打乱排版。
        if (role === "assistant" && !rawContent && metaType === "tool_call") {
          // 但如果有 reasoning_content，先累积到 pendingThinking，等待后续 assistant
          const reasoning = metadata.reasoning_content;
          if (typeof reasoning === "string" && reasoning) {
            pendingThinking = (pendingThinking ?? "") + reasoning;
          }
          continue;
        }

        if (role === "assistant") {
          // 1) 如果是独立的 think 消息（metadata.type==="think"）：
          //    暂存其内容到 pendingThinking，不创建独立卡片。
          if (metaType === "think") {
            if (contentStr) {
              pendingThinking = (pendingThinking ?? "") + contentStr;
            }
            continue;
          }

          // 2) 构建 thinking：优先使用 pendingThinking（独立 think 消息累积），
          //    否则回退 metadata.reasoning_content（tool_call 前 reasoning 内联保存）。
          let thinking: string | undefined;
          if (pendingThinking) {
            thinking = pendingThinking;
            pendingThinking = null;
          } else if (typeof metadata.reasoning_content === "string" && metadata.reasoning_content) {
            thinking = metadata.reasoning_content;
          }

          // 3) 还原 toolCalls：metadata.type==="tool_call" 时从 name/args 构造
          let toolCalls: DisplayMessage["toolCalls"] | undefined;
          if (metaType === "tool_call") {
            const toolName = typeof metadata.name === "string" ? metadata.name : "";
            let argsStr = "";
            const rawArgs = metadata.args;
            if (typeof rawArgs === "string") {
              argsStr = rawArgs;
            } else if (rawArgs != null) {
              try {
                argsStr = JSON.stringify(rawArgs);
              } catch {
                argsStr = String(rawArgs);
              }
            }
            if (toolName || argsStr) {
              const raw = toolName
                ? argsStr
                  ? `调用工具 \`${toolName}\` · ${argsStr}`
                  : `调用工具 \`${toolName}\``
                : argsStr;
              toolCalls = [{ raw, done: true }];
            }
          }

          // token 用量从 metadata 还原（后端持久化在 assistant 消息 ext.token_usage）
          let tokenUsage: DisplayMessage["tokenUsage"];
          if (
            metadata.token_usage &&
            typeof metadata.token_usage === "object" &&
            typeof (metadata.token_usage as TokenUsageInfo).total_tokens === "number"
          ) {
            tokenUsage = metadata.token_usage as TokenUsageInfo;
          }

          displayMessages.push({
            localId: nextLocalId(),
            role: "assistant",
            content: contentStr,
            thinking,
            toolCalls,
            tokenUsage,
            timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
          });
          continue;
        }

        if (role === "tool") {
          // tool 消息：追加独立的 tool 结果卡片，kind 从 metadata.type/name 推导
          const metaKind = typeof metadata.type === "string" ? metadata.type : undefined;
          const nameHint = typeof metadata.name === "string" ? metadata.name : undefined;
          const kind = nameHint ?? metaKind ?? "tool";
          displayMessages.push({
            localId: nextLocalId(),
            role: "tool",
            content: contentStr,
            toolResultKind: kind,
            timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
          });
          continue;
        }

        // user / system
        displayMessages.push({
          localId: nextLocalId(),
          role,
          content: contentStr,
          metadata: (m.metadata as Record<string, unknown> | undefined) ?? undefined,
          timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
        });
      }

      // 兜底：如果最后一条消息是独立 think，没有对应的 assistant 回复，
      // 也创建一条空 assistant 卡片保留 thinking（例如异常中断场景）。
      if (pendingThinking) {
        displayMessages.push({
          localId: nextLocalId(),
          role: "assistant",
          content: "",
          thinking: pendingThinking,
          aborted: true,
          timestamp: Date.now(),
        });
      }

      set({
        currentConversation: detail,
        messages: displayMessages,
        loadingMessages: false,
      });
    } catch (err) {
      const msg = err instanceof APIError ? err.message : String(err);
      set({ loadingMessages: false, error: `加载会话失败：${msg}` });
    }
  },

  createConversation: async () => {
    const { conversation_id } = await api.createConversation();
    await get().loadConversations();
    await get().selectConversation(conversation_id);
    return conversation_id;
  },

  deleteConversation: async (id) => {
    await api.deleteConversation(id);
    if (get().currentConversationId === id) {
      set({ currentConversationId: null, currentConversation: null, messages: [] });
    }
    await get().loadConversations();
  },

  updateConversationTitle: async (id, title) => {
    const updated = await api.updateConversationTitle(id, title);
    // 更新列表中的会话标题
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.conversation_id === id ? { ...c, title: updated.title } : c,
      ),
      // 如果是当前会话，也更新详情
      currentConversation:
        s.currentConversation?.conversation_id === id
          ? { ...s.currentConversation, title: updated.title }
          : s.currentConversation,
    }));
  },

  clearMessages: () => set({ messages: [] }),

  appendUserMessage: (content: string, metadata?: Record<string, unknown>) => {
    set((s) => ({
      messages: [
        ...s.messages,
        {
          localId: nextLocalId(),
          role: "user" as const,
          content,
          metadata,
          timestamp: Date.now(),
        },
      ],
    }));
  },

  startAssistantMessage: (_runId) => {
    set((s) => ({
      messages: [
        ...s.messages,
        {
          localId: nextLocalId(),
          role: "assistant",
          content: "",
          thinking: "",
          toolCalls: [],
          timestamp: Date.now(),
          isStreaming: true,
        },
      ],
    }));
  },

  newAssistantMessage: () => {
    set((s) => {
      const messages = [...s.messages];
      // 先把当前流式 assistant 卡片标记为完成
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].isStreaming) {
          messages[i] = { ...messages[i], isStreaming: false };
          break;
        }
      }
      messages.push({
        localId: nextLocalId(),
        role: "assistant",
        content: "",
        thinking: "",
        toolCalls: [],
        timestamp: Date.now(),
        isStreaming: true,
      });
      return { messages };
    });
  },

  updateAssistantMessage: (patch) => {
    set((s) => {
      const messages = [...s.messages];
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].isStreaming) {
          messages[i] = { ...messages[i], ...patch };
          break;
        }
      }
      return { messages };
    });
  },

  applyTokenUsage: (usage) => {
    set((s) => {
      const messages = [...s.messages];
      // 写入最后一张 assistant 卡片（本 run 的最终回复），
      // 不要求 isStreaming：token.usage 可能晚于 message.complete 到达
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === "assistant") {
          messages[i] = { ...messages[i], tokenUsage: usage };
          break;
        }
      }
      return { messages };
    });
  },

  completeAssistantMessage: () => {
    set((s) => {
      const messages = [...s.messages];
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].isStreaming) {
          messages[i] = { ...messages[i], isStreaming: false };
          break;
        }
      }
      return { messages };
    });
  },

  appendToolResultMessage: (content, kind, insertBefore) => {
    set((s) => {
      const toolMsg: DisplayMessage = {
        localId: nextLocalId(),
        role: "tool",
        content,
        toolResultKind: kind,
        timestamp: Date.now(),
      };
      if (!insertBefore) {
        return { messages: [...s.messages, toolMsg] };
      }
      // 运行时确认续跑：结果先于首个 turn.start 到达，
      // 插到最后一张流式卡片之前，保持时间顺序
      const messages = [...s.messages];
      let insertAt = messages.length;
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].isStreaming) {
          insertAt = i;
          break;
        }
      }
      messages.splice(insertAt, 0, toolMsg);
      return { messages };
    });
  },

  clearAwaitingUser: () => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.awaitingUser ? { ...m, awaitingUser: false, awaitUserSpec: null } : m,
      ),
    }));
  },

  truncateLastTurn: () => {
    set((s) => {
      let lastUserIdx = -1;
      for (let i = s.messages.length - 1; i >= 0; i--) {
        if (s.messages[i].role === "user") {
          lastUserIdx = i;
          break;
        }
      }
      if (lastUserIdx < 0) return {};
      // 保留最后一条 user 消息卡片，删除其后全部 assistant/tool 卡片
      return { messages: s.messages.slice(0, lastUserIdx + 1) };
    });
  },

  setMessages: (msgs) => set({ messages: msgs }),
}));
