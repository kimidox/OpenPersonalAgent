/**
 * 语音设置页：ASR 语音识别 / TTS 语音合成 / 音频设备。
 *
 * 对应 ui_flet/settings/voice_settings_page.py。
 * 端点：GET /api/settings/voice，PUT /api/settings/config/{key}，
 *      POST /api/recording/asr/load | /api/recording/asr/release
 *
 * 通用配置走 api.setConfig(key, value)；switch 的值以 "true"/"false" 字符串存储。
 */
import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import type { VoiceSettingsResponse } from "@/types/api";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";

type Section = "asr" | "tts" | "audio";

export default function VoiceSettingsPage() {
  const [settings, setSettings] = useState<VoiceSettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [asrBusy, setAsrBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getVoiceSettings();
      setSettings(resp);
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

  // 仅更新本地状态（用于文本输入 onChange，避免每次按键都写后端）
  const setLocalField = useCallback(
    (section: Section, key: string, value: string) => {
      setSettings((prev) => {
        if (!prev) return prev;
        return { ...prev, [section]: { ...prev[section], [key]: value } };
      });
    },
    [],
  );

  // 更新本地状态并写后端
  const commitField = useCallback(
    async (section: Section, key: string, value: string) => {
      setLocalField(section, key, value);
      setStatus(null);
      try {
        await api.setConfig(key, value);
        setStatus("已保存");
      } catch (err) {
        setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
      }
    },
    [setLocalField],
  );

  const handleLoadAsr = useCallback(async () => {
    setAsrBusy(true);
    setStatus(null);
    try {
      const modelPath = settings?.asr.ASR_REALTIME_MODEL_PATH ?? "";
      await api.loadAsrModel(modelPath || undefined);
      setStatus("ASR 模型已加载");
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setAsrBusy(false);
    }
  }, [settings]);

  const handleReleaseAsr = useCallback(async () => {
    setAsrBusy(true);
    setStatus(null);
    try {
      await api.releaseAsrModel();
      setStatus("ASR 模型已释放");
    } catch (err) {
      setStatus(`释放失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setAsrBusy(false);
    }
  }, []);

  if (loading) return <div className="settings-loading">加载中...</div>;
  if (!settings) return <div className="settings-empty">无数据</div>;

  const asrVal = (key: string) => settings.asr[key] ?? "";
  const ttsVal = (key: string) => settings.tts[key] ?? "";
  const audioVal = (key: string) => settings.audio[key] ?? "";
  const boolStr = (v: string | null | undefined) => v === "true";

  return (
    <SettingsPageLayout
      title="语音设置"
      description="管理 ASR 语音识别、TTS 语音合成与音频设备配置"
      status={status ?? undefined}
    >
      {/* ASR */}
      <SettingsSection title="ASR 语音识别" description="本地实时语音识别模型配置">
        <SettingsField label="本地模型路径" hint="如：sherpa-onnx-streaming-zipformer-zh-14M">
          <input
            className="settings-input"
            value={asrVal("ASR_REALTIME_MODEL_PATH")}
            onChange={(e) =>
              setLocalField("asr", "ASR_REALTIME_MODEL_PATH", e.target.value)
            }
            onBlur={(e) =>
              commitField("asr", "ASR_REALTIME_MODEL_PATH", e.target.value)
            }
            placeholder="模型路径或名称"
          />
        </SettingsField>
        <SettingsField label="程序启动时自动加载" hint="启动时自动加载 ASR 模型">
          <label className="settings-switch">
            <input
              type="checkbox"
              checked={boolStr(settings.asr.ASR_REALTIME_AUTO_LOAD)}
              onChange={(e) =>
                commitField(
                  "asr",
                  "ASR_REALTIME_AUTO_LOAD",
                  String(e.target.checked),
                )
              }
            />
            {boolStr(settings.asr.ASR_REALTIME_AUTO_LOAD) ? "已启用" : "未启用"}
          </label>
        </SettingsField>
        <SettingsField label="启用实时语音识别" hint="开启后录音时进行实时转写">
          <label className="settings-switch">
            <input
              type="checkbox"
              checked={boolStr(settings.asr.ASR_REALTIME_ENABLED)}
              onChange={(e) =>
                commitField(
                  "asr",
                  "ASR_REALTIME_ENABLED",
                  String(e.target.checked),
                )
              }
            />
            {boolStr(settings.asr.ASR_REALTIME_ENABLED) ? "已启用" : "未启用"}
          </label>
        </SettingsField>
        <SettingsField label="实时结果更新间隔" hint="单位毫秒，建议 100-500">
          <input
            className="settings-input"
            type="number"
            min="0"
            value={asrVal("ASR_REALTIME_UPDATE_INTERVAL")}
            onChange={(e) =>
              setLocalField("asr", "ASR_REALTIME_UPDATE_INTERVAL", e.target.value)
            }
            onBlur={(e) =>
              commitField("asr", "ASR_REALTIME_UPDATE_INTERVAL", e.target.value)
            }
          />
        </SettingsField>
        <SettingsField label="模型加载控制" hint="手动加载或释放 ASR 模型">
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="settings-btn primary"
              onClick={handleLoadAsr}
              disabled={asrBusy}
            >
              {asrBusy ? "处理中..." : "加载模型"}
            </button>
            <button
              className="settings-btn"
              onClick={handleReleaseAsr}
              disabled={asrBusy}
            >
              释放模型
            </button>
          </div>
        </SettingsField>
      </SettingsSection>

      {/* TTS */}
      <SettingsSection title="TTS 语音合成" description="文本转语音模型与音色配置">
        <SettingsField label="模型类型" hint="zh 仅中文，zh_en 中英混合">
          <select
            className="settings-select"
            value={ttsVal("TTS_MODEL_TYPE")}
            onChange={(e) =>
              commitField("tts", "TTS_MODEL_TYPE", e.target.value)
            }
          >
            <option value="zh">zh（仅中文）</option>
            <option value="zh_en">zh_en（中英混合）</option>
          </select>
        </SettingsField>
        <SettingsField label="模型路径" hint="本地模型文件路径">
          <input
            className="settings-input"
            value={ttsVal("TTS_MODEL_PATH")}
            onChange={(e) =>
              setLocalField("tts", "TTS_MODEL_PATH", e.target.value)
            }
            onBlur={(e) =>
              commitField("tts", "TTS_MODEL_PATH", e.target.value)
            }
            placeholder="模型路径"
          />
        </SettingsField>
        <SettingsField label="语速" hint="50-200，100 为标准语速">
          <input
            className="settings-input"
            type="number"
            min="50"
            max="200"
            value={ttsVal("TTS_SPEED")}
            onChange={(e) => setLocalField("tts", "TTS_SPEED", e.target.value)}
            onBlur={(e) => commitField("tts", "TTS_SPEED", e.target.value)}
          />
        </SettingsField>
        <SettingsField label="音色 ID" hint="不同模型支持的音色编号">
          <input
            className="settings-input"
            type="number"
            min="0"
            value={ttsVal("TTS_SPEAKER_ID")}
            onChange={(e) =>
              setLocalField("tts", "TTS_SPEAKER_ID", e.target.value)
            }
            onBlur={(e) =>
              commitField("tts", "TTS_SPEAKER_ID", e.target.value)
            }
          />
        </SettingsField>
        <SettingsField label="启动时自动加载" hint="启动时自动加载 TTS 模型">
          <label className="settings-switch">
            <input
              type="checkbox"
              checked={boolStr(settings.tts.TTS_AUTO_LOAD)}
              onChange={(e) =>
                commitField("tts", "TTS_AUTO_LOAD", String(e.target.checked))
              }
            />
            {boolStr(settings.tts.TTS_AUTO_LOAD) ? "已启用" : "未启用"}
          </label>
        </SettingsField>
        <SettingsField label="模型不存在时自动下载" hint="缺失模型时从网络下载">
          <label className="settings-switch">
            <input
              type="checkbox"
              checked={boolStr(settings.tts.TTS_AUTO_DOWNLOAD)}
              onChange={(e) =>
                commitField(
                  "tts",
                  "TTS_AUTO_DOWNLOAD",
                  String(e.target.checked),
                )
              }
            />
            {boolStr(settings.tts.TTS_AUTO_DOWNLOAD) ? "已启用" : "未启用"}
          </label>
        </SettingsField>
      </SettingsSection>

      {/* Audio */}
      <SettingsSection title="音频设备" description="录音输入与播放输出设备配置">
        <SettingsField label="输入设备" hint="麦克风设备名，留空使用系统默认">
          <input
            className="settings-input"
            value={audioVal("AUDIO_INPUT_DEVICE")}
            onChange={(e) =>
              setLocalField("audio", "AUDIO_INPUT_DEVICE", e.target.value)
            }
            onBlur={(e) =>
              commitField("audio", "AUDIO_INPUT_DEVICE", e.target.value)
            }
            placeholder="系统默认"
          />
        </SettingsField>
        <SettingsField label="输出设备" hint="扬声器设备名，留空使用系统默认">
          <input
            className="settings-input"
            value={audioVal("AUDIO_OUTPUT_DEVICE")}
            onChange={(e) =>
              setLocalField("audio", "AUDIO_OUTPUT_DEVICE", e.target.value)
            }
            onBlur={(e) =>
              commitField("audio", "AUDIO_OUTPUT_DEVICE", e.target.value)
            }
            placeholder="系统默认"
          />
        </SettingsField>
      </SettingsSection>
    </SettingsPageLayout>
  );
}
