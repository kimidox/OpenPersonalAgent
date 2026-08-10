import { useState } from "react";
import "./Settings.css";
import ModelConfigPage from "./ModelConfigPage";
import PromptTemplatePage from "./PromptTemplatePage";
import ScheduledTasksPage from "./ScheduledTasksPage";
import HotkeyPage from "./HotkeyPage";
import Live2DPage from "./Live2DPage";
import VoiceSettingsPage from "./VoiceSettingsPage";
import SkillsManagementPage from "./SkillsManagementPage";
import SkillTogglePage from "./SkillTogglePage";
import OtherSettingsPage from "./OtherSettingsPage";

interface SettingsPageProps {
  onBack: () => void;
}

type SettingsTab =
  | "model"
  | "skills-toggle"
  | "skills-mgmt"
  | "voice"
  | "hotkey"
  | "tasks"
  | "prompt"
  | "live2d"
  | "other";

interface TabDef {
  key: SettingsTab;
  label: string;
  icon: React.ReactNode;
}

const ICONS = {
  model: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
  skillsToggle: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="8" width="20" height="8" rx="4" />
      <circle cx="8" cy="12" r="3" fill="currentColor" />
    </svg>
  ),
  skillsMgmt: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  ),
  voice: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  ),
  hotkey: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="M6 8h.01" />
      <path d="M10 8h.01" />
      <path d="M14 8h.01" />
      <path d="M18 8h.01" />
      <path d="M8 12h.01" />
      <path d="M12 12h.01" />
      <path d="M16 12h.01" />
      <path d="M7 16h10" />
    </svg>
  ),
  tasks: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  ),
  prompt: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  ),
  live2d: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M8 14s1.5 2 4 2 4-2 4-2" />
      <line x1="9" y1="9" x2="9.01" y2="9" />
      <line x1="15" y1="9" x2="15.01" y2="9" />
    </svg>
  ),
  other: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
      <circle cx="5" cy="12" r="1" />
    </svg>
  ),
};

const TABS: TabDef[] = [
  { key: "model", label: "模型配置", icon: ICONS.model },
  { key: "skills-toggle", label: "Skill开关", icon: ICONS.skillsToggle },
  { key: "skills-mgmt", label: "用户Skill管理", icon: ICONS.skillsMgmt },
  { key: "voice", label: "语音设置", icon: ICONS.voice },
  { key: "hotkey", label: "快捷键设置", icon: ICONS.hotkey },
  { key: "tasks", label: "定时任务", icon: ICONS.tasks },
  { key: "prompt", label: "系统提示词", icon: ICONS.prompt },
  { key: "live2d", label: "2D Live", icon: ICONS.live2d },
  { key: "other", label: "其他设置", icon: ICONS.other },
];

export default function SettingsPage({ onBack }: SettingsPageProps) {
  const [tab, setTab] = useState<SettingsTab>("model");

  return (
    <div className="settings-root">
      <aside className="settings-sidebar">
        <button
          className="settings-back-btn"
          onClick={onBack}
          title="返回主页面"
        >
          ← 返回
        </button>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`settings-nav-item ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            <span className="settings-nav-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </aside>
      <main className="settings-content">
        {tab === "model" && <ModelConfigPage />}
        {tab === "prompt" && <PromptTemplatePage />}
        {tab === "tasks" && <ScheduledTasksPage />}
        {tab === "hotkey" && <HotkeyPage />}
        {tab === "live2d" && <Live2DPage />}
        {tab === "voice" && <VoiceSettingsPage />}
        {tab === "skills-mgmt" && <SkillsManagementPage />}
        {tab === "skills-toggle" && <SkillTogglePage />}
        {tab === "other" && <OtherSettingsPage />}
      </main>
    </div>
  );
}
