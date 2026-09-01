/**
 * 后端 REST API 类型（与 backend_service/schemas.py 与各 router 对齐）。
 */

export interface ConversationSummary {
  conversation_id: string;
  title: string | null;
  type: string;
  active_skill_ids: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageRecord[];
}

export interface MessageRecord {
  role: string;
  content: string;
  timestamp?: string;
  metadata?: MessageMetadata;
}

export interface MessageMetadata {
  type?: string; // "think" | "tool_call" | "plan" | "assistant"
  name?: string; // tool name
  args?: string; // tool args JSON string
  tool_call_id?: string;
  reasoning_content?: string; // thinking/reasoning content (tool_call scenario)
  token_usage?: Record<string, unknown>;
  files?: unknown[];
  [key: string]: unknown;
}

export interface SendMessageRequest {
  query: string;
  enable_thinking?: boolean;
  uploaded_files_content?: string | Record<string, unknown> | null;
  queued_ok?: boolean;
  source?: "main" | "floating_ball" | "scheduler";
}

export interface RegenerateRequest {
  enable_thinking?: boolean;
  queued_ok?: boolean;
}

export interface SendMessageStartedResponse {
  status: "started";
  run_id: string;
}

export interface SendMessageQueuedResponse {
  status: "queued";
  run_id: string;
  position: number;
}

export interface AgentStatus {
  is_running: boolean;
  active_run_id: string | null;
  active_conversation_id: string | null;
  queue_size: number;
}

export interface HealthResponse {
  status: "ok";
  uptime_s: number;
  skill_agent_ready: boolean;
  scheduler_running: boolean;
  active_runs: number;
  queue_size: number;
  ws_clients: number;
}

export interface SkillSummary {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  is_disabled: boolean;
}

export interface CliPackageSummary {
  name: string;
  version: string;
  description: string;
  entry: string;
  install_dir: string;
  commands: Array<{ usage: string; desc: string }>;
}

export interface LLMConfigItem {
  id: string | null;
  name: string;
  model_name: string;
  api_key: string;
  base_url: string;
  temperature: number;
  top_p: number;
  frequency_penalty: number;
  enable_thinking: boolean;
  enable_vision: boolean;
}

export interface LLMConfigListResponse {
  configs: LLMConfigItem[];
  active_id: string | null;
  auto_switch_on_failure: boolean;
}

export interface ScheduledTaskResponse {
  task_id: string;
  user_id: string;
  title: string;
  content: string;
  trigger_time: string;
  repeat_type: string;
  notification_type: string;
  status: string;
  execution_type: string;
  execution_chain: string | null;
  source_conversation_id: string | null;
  skill_ids: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ScheduledTaskCreate {
  title: string;
  content: string;
  trigger_time: string;
  repeat_type?: string;
  notification_type?: string;
  execution_type?: string;
  execution_chain?: string | null;
  source_conversation_id?: string | null;
  skill_ids?: string[];
}

export type ScheduledTaskUpdate = Partial<ScheduledTaskCreate> & {
  status?: string;
};

// ---------------------------------------------------------------------
// 设置页通用
// ---------------------------------------------------------------------

export interface ConfigValueResponse {
  key: string;
  value: string | null;
}

export interface AutostartResponse {
  enabled: boolean;
  detail: Record<string, unknown> | null;
}

export interface PromptTemplatesResponse {
  templates: Record<string, string>;
}

export interface VoiceSettingsResponse {
  asr: Record<string, string | null>;
  tts: Record<string, string | null>;
  audio: Record<string, string | null>;
}

export interface Live2DSettingsResponse {
  enabled: boolean;
  auto_load: boolean;
  model_name: string;
  width: number;
  height: number;
}

export interface Live2DModelItem {
  name: string;
  dir_name: string;
}

export interface Live2DModelsResponse {
  models: Live2DModelItem[];
}

// ---------------------------------------------------------------------
// 技能
// ---------------------------------------------------------------------

export interface SkillBindingsResponse {
  bindings: Record<string, string[]>;
}

export interface InstallSkillResponse {
  installed: string[];
  message: string;
}

// ---------------------------------------------------------------------
// 录音
// ---------------------------------------------------------------------

export interface RecordingStatusResponse {
  is_recording: boolean;
  asr_model_loaded: boolean;
  current_audio_path: string | null;
}

// ---------------------------------------------------------------------
// TTS
// ---------------------------------------------------------------------

export interface TtsStatusResponse {
  loaded: boolean;
  model_path: string | null;
  num_speakers: number;
}

export interface TtsSpeakRequest {
  text: string;
  speaker_id?: number;
  speed?: number;
}

export interface StartRecordingResponse {
  started: boolean;
  conversation_id: string | null;
}

export interface StopRecordingResponse {
  stopped: boolean;
  audio_path: string | null;
}

export interface LoadModelResponse {
  loaded: boolean;
}

export interface ReleaseModelResponse {
  released: boolean;
}

// ---------------------------------------------------------------------
// 文件上传
// ---------------------------------------------------------------------

export interface UploadResponse {
  file_id: string;
  original_name: string;
  file_size: number;
  mime_type: string | null;
  parsed_text: string;
  parsed_pages: number;
}

export interface FileAttachment {
  file_id: string;
  original_name: string;
  file_size: number;
  mime_type: string | null;
  parsed_pages: number;
  summary: string;
  // 解析出的纯文本内容，供 SkillAgent 拼接到用户 query
  parsed_text: string;
}

export interface SetUploadedContentResponse {
  set: boolean;
}

export interface CleanupResponse {
  deleted_count: number;
  total_size: number;
}

// ---------------------------------------------------------------------
// Agent 扩展
// ---------------------------------------------------------------------

export interface ConstraintsResponse {
  constraints: string;
}

export interface BaseInfoResponse {
  base_info: string;
}

// ---------------------------------------------------------------------
// 悬浮球（阶段 5）
// ---------------------------------------------------------------------

export interface FloatingBallStatus {
  running: boolean;
  pid: number | null;
  ipc_stats: Record<string, unknown> | null;
}
