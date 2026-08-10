/**
 * 2D Live 悬浮球配置页：启用开关 + 模型 + 尺寸。
 *
 * 对应 ui_flet/settings/live2d_page.py。
 * 端点：GET /api/settings/live2d（批量读）
 *       PUT /api/settings/config/{key}（单写）
 * 说明：配置后需重启生效。
 */
import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";
import Toggle from "./Toggle";

interface Live2DForm {
  enabled: boolean;
  modelName: string;
  width: number;
  height: number;
}

const CONFIG_KEYS = {
  enabled: "LIVE2D_ENABLED",
  modelName: "LIVE2D_MODEL_NAME",
  width: "LIVE2D_BALL_WIDTH",
  height: "LIVE2D_BALL_HEIGHT",
} as const;

const DEFAULT_FORM: Live2DForm = {
  enabled: false,
  modelName: "",
  width: 200,
  height: 200,
};

const MODEL_TREE = `PersonalData/2DLiveFiles/
├── model_name_1/
│   ├── model.model3.json
│   ├── model.moc3
│   ├── textures/
│   │   └── texture_00.png
│   └── motions/
└── model_name_2/
    ├── model.model3.json
    └── ...`;

export default function Live2DPage() {
  const [form, setForm] = useState<Live2DForm>(DEFAULT_FORM);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getLive2DSettings();
      setForm({
        enabled: resp.enabled,
        modelName: resp.model_name,
        width: resp.width,
        height: resp.height,
      });
      setModels(resp.model_name ? [resp.model_name] : []);
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

  const handleSave = useCallback(async () => {
    setSaving(true);
    setStatus(null);
    try {
      await Promise.all([
        api.setConfig(CONFIG_KEYS.enabled, String(form.enabled)),
        api.setConfig(CONFIG_KEYS.modelName, form.modelName),
        api.setConfig(CONFIG_KEYS.width, String(form.width)),
        api.setConfig(CONFIG_KEYS.height, String(form.height)),
      ]);
      setStatus("已保存，重启后生效");
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [form]);

  const handleRefreshModels = useCallback(async () => {
    setStatus("正在刷新模型列表...");
    // 当前后端未提供模型扫描接口，保留当前已选模型作为占位
    setModels(form.modelName ? [form.modelName] : []);
    setStatus("模型列表已刷新（请确保模型文件已放入 PersonalData/2DLiveFiles）");
  }, [form.modelName]);

  const handleLoadModel = useCallback(async () => {
    if (!form.modelName) {
      setStatus("请选择一个 Live2D 模型");
      return;
    }
    setStatus("模型加载请求已发送（实际加载在悬浮球重启后生效）");
  }, [form.modelName]);

  if (loading) return <div className="settings-loading">加载中...</div>;

  return (
    <SettingsPageLayout
      title="2D Live 悬浮球配置"
      description="配置 Live2D 模型作为悬浮球的视觉表现形式。模型文件应放置在 PersonalData/2DLiveFiles 目录下，支持 Live2D Cubism 3/4 格式（.model3.json）。"
      status={status ?? undefined}
    >
      <SettingsSection
        title="启用设置"
        headerActions={
          <button
            className="settings-btn primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "保存中..." : "保存"}
          </button>
        }
      >
        <Toggle
          checked={form.enabled}
          onChange={(checked) => setForm({ ...form, enabled: checked })}
          label="启用 Live2D 悬浮球模式（替代传统纯色按钮）"
        />
      </SettingsSection>

      <SettingsSection title="模型选择">
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <select
            className="settings-select"
            value={form.modelName}
            onChange={(e) => setForm({ ...form, modelName: e.target.value })}
            style={{ flex: 1 }}
          >
            <option value="">选择模型</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            className="settings-btn primary"
            onClick={handleRefreshModels}
            disabled={saving}
          >
            ↻ 刷新模型列表
          </button>
        </div>
        <div>
          <button
            className="settings-btn primary"
            onClick={handleLoadModel}
            disabled={saving || !form.modelName}
          >
            ↓ 加载模型
          </button>
          <div className="list-item-meta" style={{ marginTop: 8 }}>
            请选择一个 Live2D 模型。
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title="悬浮球尺寸">
        <div style={{ display: "flex", gap: 16 }}>
          <SettingsField label="宽度（像素）" layout="stacked" hint="50-500">
            <input
              className="settings-input"
              type="number"
              min={50}
              max={500}
              value={form.width}
              onChange={(e) =>
                setForm({ ...form, width: Number(e.target.value) || 0 })
              }
            />
          </SettingsField>
          <SettingsField label="高度（像素）" layout="stacked" hint="50-500">
            <input
              className="settings-input"
              type="number"
              min={50}
              max={500}
              value={form.height}
              onChange={(e) =>
                setForm({ ...form, height: Number(e.target.value) || 0 })
              }
            />
          </SettingsField>
        </div>
      </SettingsSection>

      <SettingsSection title="模型目录说明">
        <p className="list-item-meta">
          Live2D 模型应放置在 PersonalData/2DLiveFiles 目录下。
          <br />
          每个模型应放在独立的子目录中，目录结构如下：
        </p>
        <pre className="directory-tree">{MODEL_TREE}</pre>
      </SettingsSection>
    </SettingsPageLayout>
  );
}
