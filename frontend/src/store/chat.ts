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
  MessageRecord,
} from "@/types/api";

export interface DisplayMessage {
  // 本地生成的唯一 id（用于 React key）
  localId: string;
  role: "user" | "assistant" | "system" | "tool";
  // 用户消息：直接文本；assistant 消息：分 thinking / content / toolCalls 三段；tool 消息：工具结果文本
  content: string;
  thinking?: string;
  toolCalls?: { raw: string; result?: unknown; done: boolean }[];
  // tool 结果卡片的来源 kind（base_tool / tool）
  toolResultKind?: string;
  timestamp: number;
  // 该 assistant 消息是否仍在流式中（用于打字机渲染）
  isStreaming?: boolean;
  // 是否因 sidecar 重启被中断
  aborted?: boolean;
  // 是否等待用户回复
  awaitingUser?: boolean;
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
  clearMessages: () => void;

  // 实时消息操作（由 useStream 调用）
  appendUserMessage: (content: string) => void;
  startAssistantMessage: (runId: string) => void;
  // 开启下一轮 assistant 卡片（模型新一轮发言前调用）
  newAssistantMessage: () => void;
  updateAssistantMessage: (patch: Partial<DisplayMessage>) => void;
  completeAssistantMessage: () => void;
  // 追加一条独立的工具结果卡片
  appendToolResultMessage: (content: string, kind?: string) => void;
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
      set({ conversations, loadingConversations: false });
    } catch (err) {
      const msg = err instanceof APIError ? err.message : String(err);
      set({ loadingConversations: false, error: `加载会话列表失败：${msg}` });
    }
  },

  selectConversation: async (id) => {
    set({ loadingMessages: true, currentConversationId: id, error: null });
    try {
      const detail = await api.getConversation(id);
      const messages: DisplayMessage[] = detail.messages
        // 跳过仅用于保存 tool_calls 元数据、没有实际文本的 assistant 记录，
        // 避免历史加载后出现大量空 assistant 卡片打乱排版。
        .filter(
          (m) =>
            !(m.role === "assistant" && !m.content && m.metadata?.type === "tool_call"),
        )
        .map((m: MessageRecord) => ({
          localId: nextLocalId(),
          role: (m.role as "user" | "assistant" | "system" | "tool") ?? "assistant",
          content: typeof m.content === "string" ? m.content : JSON.stringify(m.content),
          timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
        }));
      set({
        currentConversation: detail,
        messages,
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

  clearMessages: () => set({ messages: [] }),

  appendUserMessage: (content) => {
    set((s) => ({
      messages: [
        ...s.messages,
        {
          localId: nextLocalId(),
          role: "user",
          content,
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

  appendToolResultMessage: (content, kind) => {
    set((s) => ({
      messages: [
        ...s.messages,
        {
          localId: nextLocalId(),
          role: "tool",
          content,
          toolResultKind: kind,
          timestamp: Date.now(),
        },
      ],
    }));
  },

  setMessages: (msgs) => set({ messages: msgs }),
}));
