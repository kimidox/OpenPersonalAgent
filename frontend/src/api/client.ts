/**
 * REST 客户端：fetchWithRetry + token 注入。
 *
 * 见 frontend-tauri-refactor.md 3.13 节。
 * - 网络错误指数退避 3 次（200ms / 600ms / 1.8s）
 * - 失败 → 上层 toast；连续 3 次失败 → 全局"后端连接中断"提示
 * - token：开发期为空（dev 模式后端跳过校验）；打包期由 Tauri Rust 注入
 */

import type {
  AgentStatus,
  AutostartResponse,
  BaseInfoResponse,
  ConfigValueResponse,
  ConstraintsResponse,
  ConversationDetail,
  ConversationSummary,
  CleanupResponse,
  FloatingBallStatus,
  HealthResponse,
  InstallSkillResponse,
  LLMConfigItem,
  LLMConfigListResponse,
  Live2DSettingsResponse,
  LoadModelResponse,
  PromptTemplatesResponse,
  RecordingStatusResponse,
  ReleaseModelResponse,
  ScheduledTaskCreate,
  ScheduledTaskResponse,
  ScheduledTaskUpdate,
  SendMessageRequest,
  SendMessageStartedResponse,
  SendMessageQueuedResponse,
  SetUploadedContentResponse,
  SkillBindingsResponse,
  SkillSummary,
  StartRecordingResponse,
  StopRecordingResponse,
  UploadResponse,
  VoiceSettingsResponse,
} from "@/types/api";
import { getBaseUrl, getToken } from "./backend";

// 全局连接中断监听器（由 ChatPage 注册）
type ConnectionListener = (online: boolean) => void;
const connectionListeners = new Set<ConnectionListener>();

export function onConnectionChange(listener: ConnectionListener): () => void {
  connectionListeners.add(listener);
  return () => connectionListeners.delete(listener);
}

let consecutiveFailures = 0;
function notifyConnection(online: boolean): void {
  consecutiveFailures = online ? 0 : consecutiveFailures + 1;
  // 连续 3 次失败才触发中断提示；任何成功立即恢复
  if (!online && consecutiveFailures === 3) {
    connectionListeners.forEach((l) => l(false));
  } else if (online) {
    connectionListeners.forEach((l) => l(true));
  }
}

export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "APIError";
  }
}

/**
 * 带重试的 fetch。网络错误指数退避 3 次。
 * HTTP 4xx/5xx 不重试（业务错误）。
 */
async function fetchWithRetry(
  url: string,
  init: RequestInit = {},
  retries = 3,
): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  const tkn = getToken();
  if (tkn) headers.set("X-Backend-Token", tkn);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const fullUrl = url.startsWith("http") ? url : `${getBaseUrl()}${url}`;
  let lastErr: unknown;

  for (let i = 0; i < retries; i++) {
    try {
      const resp = await fetch(fullUrl, { ...init, headers });
      notifyConnection(true);
      return resp;
    } catch (err) {
      lastErr = err;
      // 网络错误才重试
      const backoff = 200 * 3 ** i; // 200 / 600 / 1800
      await new Promise((r) => setTimeout(r, backoff));
    }
  }
  notifyConnection(false);
  throw lastErr instanceof Error
    ? lastErr
    : new Error("网络请求失败（重试 3 次仍失败）");
}

async function request<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const resp = await fetchWithRetry(url, init);
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new APIError(resp.status, `HTTP ${resp.status}`, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

/**
 * 上传文件专用：multipart/form-data，不预设 Content-Type（让浏览器设 boundary）。
 */
async function uploadFile<T>(
  url: string,
  file: File,
  fieldName = "file",
): Promise<T> {
  const form = new FormData();
  form.append(fieldName, file);
  const headers = new Headers();
  const tkn = getToken();
  if (tkn) headers.set("X-Backend-Token", tkn);
  const fullUrl = url.startsWith("http") ? url : `${getBaseUrl()}${url}`;
  let lastErr: unknown;
  for (let i = 0; i < 3; i++) {
    try {
      const resp = await fetch(fullUrl, { method: "POST", body: form, headers });
      notifyConnection(true);
      if (!resp.ok) {
        let detail: unknown;
        try {
          detail = await resp.json();
        } catch {
          detail = await resp.text();
        }
        throw new APIError(resp.status, `HTTP ${resp.status}`, detail);
      }
      return (await resp.json()) as T;
    } catch (err) {
      if (err instanceof APIError) throw err;
      lastErr = err;
      await new Promise((r) => setTimeout(r, 200 * 3 ** i));
    }
  }
  notifyConnection(false);
  throw lastErr instanceof Error
    ? lastErr
    : new Error("文件上传失败（重试 3 次仍失败）");
}

// =====================================================================
// API 模块
// =====================================================================

export const api = {
  // 健康检查
  health: () => request<HealthResponse>("/api/health"),
  ready: () => request<{ ready: boolean }>("/api/ready"),

  // 会话
  listConversations: () =>
    request<ConversationSummary[]>("/api/conversations"),
  getConversation: (id: string) =>
    request<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: (type = "agent_conversation") =>
    request<{ conversation_id: string; title: string }>(
      "/api/conversations",
      { method: "POST", body: JSON.stringify({ conversation_type: type }) },
    ),
  deleteConversation: (id: string) =>
    request<void>(`/api/conversations/${id}`, { method: "DELETE" }),
  updateConversationTitle: (id: string, title: string) =>
    request<ConversationSummary>(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  // 消息
  sendMessage: (conversationId: string, body: SendMessageRequest) =>
    request<SendMessageStartedResponse | SendMessageQueuedResponse>(
      `/api/conversations/${conversationId}/messages`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  stopConversation: (conversationId: string) =>
    request<{ stopped: boolean; run_id: string | null }>(
      `/api/conversations/${conversationId}/stop`,
      { method: "POST" },
    ),
  stopAgent: () =>
    request<{ stopped: boolean; run_id: string | null }>(
      "/api/agent/stop",
      { method: "POST" },
    ),

  // Agent 状态与控制
  agentStatus: () => request<AgentStatus>("/api/agent/status"),
  agentThinking: () => request<{ enabled: boolean }>("/api/agent/thinking"),
  setAgentThinking: (enabled: boolean) =>
    request<{ enabled: boolean }>("/api/agent/thinking", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  agentSteer: (message: string) =>
    request<{ accepted: boolean }>("/api/agent/steer", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  agentFollowup: (message: string) =>
    request<{ accepted: boolean }>("/api/agent/followup", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  agentConstraints: () =>
    request<ConstraintsResponse>("/api/agent/constraints"),
  setAgentConstraints: (constraints: string) =>
    request<ConstraintsResponse>("/api/agent/constraints", {
      method: "PUT",
      body: JSON.stringify({ constraints }),
    }),
  clearAgentConstraints: () =>
    request<ConstraintsResponse>("/api/agent/constraints", {
      method: "DELETE",
    }),
  agentBaseInfo: () =>
    request<BaseInfoResponse>("/api/agent/base-info"),
  reloadSkills: () =>
    request<{ reloaded: boolean }>("/api/agent/reload-skills", {
      method: "POST",
    }),
  clearCache: () =>
    request<{ cleared: boolean }>("/api/agent/clear-cache", { method: "POST" }),

  // -------------------------------------------------------------------
  // 技能
  // -------------------------------------------------------------------
  listSkills: () => request<SkillSummary[]>("/api/skills"),
  listUserSkills: () => request<SkillSummary[]>("/api/skills/user"),
  listBuiltinSkills: () => request<SkillSummary[]>("/api/skills/builtin"),
  toggleSkill: (skillId: string, disabled: boolean) =>
    request<SkillSummary>(`/api/skills/${skillId}/toggle`, {
      method: "PUT",
      body: JSON.stringify({ disabled }),
    }),
  getSkillBindings: () =>
    request<SkillBindingsResponse>("/api/skills/bindings"),
  setSkillBindings: (bindings: Record<string, string[]>) =>
    request<SkillBindingsResponse>("/api/skills/bindings", {
      method: "PUT",
      body: JSON.stringify({ bindings }),
    }),
  deleteSkill: (skillId: string) =>
    request<void>(`/api/skills/${skillId}`, { method: "DELETE" }),
  installSkill: (file: File) =>
    uploadFile<InstallSkillResponse>("/api/skills/install", file),

  // -------------------------------------------------------------------
  // LLM 配置
  // -------------------------------------------------------------------
  listLLMConfigs: () =>
    request<LLMConfigListResponse>("/api/settings/llm"),
  addLLMConfig: (body: LLMConfigItem) =>
    request<LLMConfigItem>("/api/settings/llm", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateLLMConfig: (configId: string, body: LLMConfigItem) =>
    request<LLMConfigItem>(`/api/settings/llm/${configId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteLLMConfig: (configId: string) =>
    request<void>(`/api/settings/llm/${configId}`, { method: "DELETE" }),
  setActiveLLM: (configId: string) =>
    request<{ active_id: string }>("/api/settings/llm/active", {
      method: "PUT",
      body: JSON.stringify({ config_id: configId }),
    }),

  // -------------------------------------------------------------------
  // 提示词模板
  // -------------------------------------------------------------------
  listPromptTemplates: () =>
    request<PromptTemplatesResponse>("/api/settings/prompt-templates"),
  updatePromptTemplate: (conversationType: string, template: string) =>
    request<{ updated: string }>(
      `/api/settings/prompt-templates/${conversationType}`,
      { method: "PUT", body: JSON.stringify({ template }) },
    ),
  resetPromptTemplate: (conversationType: string) =>
    request<{ reset: string }>(
      `/api/settings/prompt-templates/${conversationType}`,
      { method: "DELETE" },
    ),
  resetAllPromptTemplates: () =>
    request<{ reset_all: boolean }>("/api/settings/prompt-templates/reset", {
      method: "POST",
    }),

  // -------------------------------------------------------------------
  // 计划任务
  // -------------------------------------------------------------------
  listScheduledTasks: (statusFilter?: string) =>
    request<ScheduledTaskResponse[]>(
      statusFilter
        ? `/api/settings/scheduled-tasks?status_filter=${encodeURIComponent(statusFilter)}`
        : "/api/settings/scheduled-tasks",
    ),
  createScheduledTask: (body: ScheduledTaskCreate) =>
    request<ScheduledTaskResponse>("/api/settings/scheduled-tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getScheduledTask: (taskId: string) =>
    request<ScheduledTaskResponse>(`/api/settings/scheduled-tasks/${taskId}`),
  updateScheduledTask: (taskId: string, body: ScheduledTaskUpdate) =>
    request<ScheduledTaskResponse>(`/api/settings/scheduled-tasks/${taskId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteScheduledTask: (taskId: string) =>
    request<void>(`/api/settings/scheduled-tasks/${taskId}`, {
      method: "DELETE",
    }),

  // -------------------------------------------------------------------
  // 开机自启
  // -------------------------------------------------------------------
  getAutostart: () =>
    request<AutostartResponse>("/api/settings/autostart"),
  enableAutostart: () =>
    request<AutostartResponse>("/api/settings/autostart/enable", {
      method: "POST",
    }),
  disableAutostart: () =>
    request<AutostartResponse>("/api/settings/autostart/disable", {
      method: "POST",
    }),

  // -------------------------------------------------------------------
  // 通用 .env 配置（hotkey / live2d 写入 / voice 写入均走此通道）
  // -------------------------------------------------------------------
  getConfig: (key: string) =>
    request<ConfigValueResponse>(`/api/settings/config/${key}`),
  setConfig: (key: string, value: string) =>
    request<ConfigValueResponse>(`/api/settings/config/${key}`, {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    }),

  // -------------------------------------------------------------------
  // 批量配置读取（语音 / Live2D）
  // -------------------------------------------------------------------
  getVoiceSettings: () =>
    request<VoiceSettingsResponse>("/api/settings/voice"),
  getLive2DSettings: () =>
    request<Live2DSettingsResponse>("/api/settings/live2d"),

  // -------------------------------------------------------------------
  // 录音
  // -------------------------------------------------------------------
  recordingStatus: () =>
    request<RecordingStatusResponse>("/api/recording/status"),
  startRecording: (conversationId?: string) =>
    request<StartRecordingResponse>(
      conversationId
        ? `/api/recording/start?conversation_id=${encodeURIComponent(conversationId)}`
        : "/api/recording/start",
      { method: "POST" },
    ),
  stopRecording: () =>
    request<StopRecordingResponse>("/api/recording/stop", { method: "POST" }),
  loadAsrModel: (modelPath?: string, autoDownload?: boolean) =>
    request<LoadModelResponse>("/api/recording/asr/load", {
      method: "POST",
      body: JSON.stringify({ model_path: modelPath, auto_download: autoDownload }),
    }),
  releaseAsrModel: () =>
    request<ReleaseModelResponse>("/api/recording/asr/release", {
      method: "POST",
    }),
  transcribeAudio: (audioPath: string) =>
    request<{ text: string }>(
      `/api/recording/asr/transcribe?audio_path=${encodeURIComponent(audioPath)}`,
      { method: "POST" },
    ),

  // -------------------------------------------------------------------
  // 文件上传
  // -------------------------------------------------------------------
  uploadFile: (file: File) =>
    uploadFile<UploadResponse>("/api/files/upload", file),
  setUploadedContent: (content: string | Record<string, unknown>) =>
    request<SetUploadedContentResponse>("/api/files/set-content", {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  deleteFile: (fileId: string) =>
    request<void>(`/api/files/${fileId}`, { method: "DELETE" }),
  cleanupFiles: (maxAgeHours = 24) =>
    request<CleanupResponse>(
      `/api/files/cleanup?max_age_hours=${maxAgeHours}`,
      { method: "POST" },
    ),

  // -------------------------------------------------------------------
  // 悬浮球控制（阶段 5）
  // -------------------------------------------------------------------
  getFloatingBallStatus: () =>
    request<FloatingBallStatus>("/api/floating-ball/status"),
  showFloatingBall: () =>
    request<{ shown: boolean }>("/api/floating-ball/show", { method: "POST" }),
  hideFloatingBall: () =>
    request<{ hidden: boolean }>("/api/floating-ball/hide", { method: "POST" }),
  setFloatingBallTheme: (theme: string) =>
    request<{ theme: string }>("/api/floating-ball/theme", {
      method: "PUT",
      body: JSON.stringify({ theme }),
    }),
  restartFloatingBall: () =>
    request<{ restarted: boolean }>("/api/floating-ball/restart", {
      method: "POST",
    }),
};
