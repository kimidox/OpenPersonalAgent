/**
 * 快捷键设置页：6 个全局快捷键的查看与修改。
 *
 * 对应 ui_flet/settings/hotkey_page.py。
 * 端点：GET/PUT /api/settings/config/{key}
 * 说明：浏览器无法全局捕获快捷键，故 input 只读，通过 prompt() 输入新值。
 */
import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import { SettingsPageLayout, SettingsSection } from "./SettingsSection";

interface HotkeyDef {
  key: string;
  name: string;
  description: string;
  defaultValue: string;
}

const HOTKEYS: HotkeyDef[] = [
  { key: "HOTKEY_RECORD", name: "录音快捷键", description: "开始/停止录音", defaultValue: "ctrl+r" },
  { key: "HOTKEY_SHOW_WINDOW", name: "显示窗口快捷键", description: "显示/隐藏主窗口", defaultValue: "ctrl+shift+w" },
  { key: "HOTKEY_SEND_MESSAGE", name: "发送消息快捷键", description: "发送当前输入的消息", defaultValue: "enter" },
  { key: "HOTKEY_NEW_CONVERSATION", name: "新建会话快捷键", description: "创建新的会话", defaultValue: "ctrl+n" },
  { key: "HOTKEY_SETTINGS", name: "打开设置快捷键", description: "打开设置对话框", defaultValue: "ctrl+," },
  { key: "HOTKEY_NEWLINE", name: "输入换行快捷键", description: "在输入框中插入换行符", defaultValue: "ctrl+enter" },
];

function formatShortcut(value: string): string {
  return value
    .split("+")
    .map((p) => p.trim().toUpperCase())
    .join("+");
}

export default function HotkeyPage() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.all(
        HOTKEYS.map(async (h) => {
          const resp = await api.getConfig(h.key);
          return {
            key: h.key,
            value: resp.value && resp.value.trim() ? resp.value : h.defaultValue,
          };
        }),
      );
      const map: Record<string, string> = {};
      for (const r of results) map[r.key] = r.value;
      setValues(map);
      setStatus(null);
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const saveOne = useCallback(async (key: string, value: string) => {
    setSaving(true);
    setStatus(null);
    try {
      await api.setConfig(key, value);
      setValues((prev) => ({ ...prev, [key]: value }));
      setStatus(`已保存：${value}`);
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, []);

  const handleEdit = useCallback(
    (h: HotkeyDef) => {
      const current = values[h.key] ?? h.defaultValue;
      const next = window.prompt(
        `修改快捷键：${h.name}\n格式：ctrl+shift+x / ctrl+enter / enter 等`,
        current,
      );
      if (next === null) return;
      const trimmed = next.trim();
      if (!trimmed) {
        setStatus("快捷键不能为空");
        return;
      }
      void saveOne(h.key, trimmed);
    },
    [values, saveOne],
  );

  const handleResetOne = useCallback(
    (h: HotkeyDef) => {
      void saveOne(h.key, h.defaultValue);
    },
    [saveOne],
  );

  const handleResetAll = useCallback(async () => {
    if (!confirm("确认重置所有快捷键为默认值？")) return;
    setSaving(true);
    setStatus(null);
    try {
      await Promise.all(
        HOTKEYS.map((h) => api.setConfig(h.key, h.defaultValue)),
      );
      const map: Record<string, string> = {};
      for (const h of HOTKEYS) map[h.key] = h.defaultValue;
      setValues(map);
      setStatus("所有快捷键已重置");
    } catch (err) {
      setStatus(`重置失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, []);

  if (loading) return <div className="settings-loading">加载中...</div>;

  return (
    <SettingsPageLayout
      title="快捷键设置"
      description="点击快捷键输入框，然后按下新的快捷键组合进行修改。"
      status={status ?? undefined}
    >
      <SettingsSection title="快捷键列表">
        <div className="hotkey-list">
          {HOTKEYS.map((h) => (
            <div key={h.key} className="hotkey-row">
              <div className="hotkey-info">
                <div className="hotkey-name">{h.name}</div>
                <div className="hotkey-desc">{h.description}</div>
              </div>
              <input
                className="settings-input hotkey-input"
                value={formatShortcut(values[h.key] ?? h.defaultValue)}
                readOnly
                onClick={() => handleEdit(h)}
              />
              <button
                className="settings-btn icon-only ghost"
                onClick={() => handleResetOne(h)}
                disabled={saving}
                title="重置为默认"
              >
                ↺
              </button>
            </div>
          ))}
        </div>
      </SettingsSection>

      <div className="page-actions">
        <button
          className="settings-btn"
          onClick={handleResetAll}
          disabled={saving}
        >
          ↺ 重置所有快捷键
        </button>
      </div>
    </SettingsPageLayout>
  );
}
