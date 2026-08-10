// Tauri 应用入口（阶段 6）。
// 防止 Windows Release 构建额外弹出控制台窗口。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    personal_window_glm_lib::run()
}
