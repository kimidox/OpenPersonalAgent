import { SettingsPageLayout, SettingsSection } from "./SettingsSection";

export default function OtherSettingsPage() {
  return (
    <SettingsPageLayout
      title="其他设置"
      description="其他未归类配置项（当前暂无）"
    >
      <SettingsSection title="暂无其他设置">
        <div className="settings-empty">该分类下暂无可用配置</div>
      </SettingsSection>
    </SettingsPageLayout>
  );
}
