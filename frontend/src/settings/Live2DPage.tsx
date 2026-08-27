/**
 * 2D Live 悬浮球配置页：启用开关 + 自动加载 + 模型 + 尺寸。
 *
 * 对应 ui_flet/settings/live2d_page.py。
 * 端点：GET /api/settings/live2d（批量读）
 *       GET /api/settings/live2d/models（扫描 PersonalData/2DLiveFiles）
 *       PUT /api/settings/config/{key}（单写）
 *       POST /api/floating-ball/restart（重启悬浮球使配置生效）
 */
import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";
import Toggle from "./Toggle";
import type { Live2DModelItem } from "@/types/api";

interface Live2DForm {
  enabled: boolean;
  autoLoad: boolean;
  modelName: string;
  width: number;
  height: number;
}

const CONFIG_KEYS = {
  enabled: "LIVE2D_ENABLED",
  autoLoad: "LIVE2D_AUTO_LOAD",
  modelName: "LIVE2D_MODEL_NAME",
  width: "LIVE2D_BALL_WIDTH",
  height: "LIVE2D_BALL_HEIGHT",
} as const;

const DEFAULT_FORM: Live2DForm = {
  enabled: false,
  autoLoad: true,
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
  const [models, setModels] = useState<Live2DModelItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const loadModels = useCallback(async () => {
    try {
      const resp = await api.getLive2DModels();
      setModels(resp.models);
      return resp.models;
    } catch (err) {
      setStatus(`模型列表加载失败：${err instanceof APIError ? err.detail : err}`);
      return null;
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getLive2DSettings();
      setForm({
        enabled: resp.enabled,
        autoLoad: resp.auto_load,
        modelName: resp.model_name,
        width: resp.width,
        height: resp.height,
      });
      setStatus(null);
      await loadModels();
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setLoading(false);
    }
  }, [loadModels]);

  useEffect(() => {
    load();
  }, [load]);

  const saveForm = useCallback(async (f: Live2DForm) => {
    await Promise.all([
      api.setConfig(CONFIG_KEYS.enabled, String(f.enabled)),
      api.setConfig(CONFIG_KEYS.autoLoad, String(f.autoLoad)),
      api.setConfig(CONFIG_KEYS.modelName, f.modelName),
      api.setConfig(CONFIG_KEYS.width, String(f.width)),
      api.setConfig(CONFIG_KEYS.height, String(f.height)),
    ]);
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setStatus(null);
    try {
      await saveForm(form);
      setStatus("已保存（重启悬浮球或应用后生效）");
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [form, saveForm]);

  const handleRefreshModels = useCallback(async () => {
    setStatus("正在刷新模型列表...");
    const list = await loadModels();
    if (list) {
      setStatus(
        list.length > 0
          ? `已扫描到 ${list.length} 个模型`
          : "未发现模型（请将模型目录放入 PersonalData/2DLiveFiles）",
      );
    }
  }, [loadModels]);

  const handleLoadModel = useCallback(async () => {
    if (!form.modelName) {
      setStatus("请选择一个 Live2D 模型");
      return;
    }
    setSaving(true);
    setStatus(null);
    try {
      // 先保存当前配置（强制启用），再以 Live2D 模式重启悬浮球
      const next: Live2DForm = { ...form, enabled: true };
      await saveForm(next);
      setForm(next);
      await api.restartFloatingBall({ live2d: true });
      setStatus("模型已加载（悬浮球已重启）");
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [form, saveForm]);

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
        <Toggle
          checked={form.autoLoad}
          onChange={(checked) => setForm({ ...form, autoLoad: checked })}
          label="启动时自动加载 Live2D 模型（关闭后悬浮球以默认圆形启动，可点击下方“加载模型”手动加载）"
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
              <option key={m.dir_name} value={m.dir_name}>
                {m.name}
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
            点击“加载模型”将保存当前配置并重启悬浮球（立即生效）。
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
