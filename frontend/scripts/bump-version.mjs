/**
 * 版本自动递增脚本（patch +0.0.1）。
 *
 * 用法：npm run tauri:build
 *   打包成功后自动执行本脚本，为下一次打包准备好新版本号：
 *   1. 读取 src-tauri/tauri.conf.json 的当前版本号
 *   2. patch 位 +1（如 1.0.0 -> 1.0.1）
 *   3. 同步写回 tauri.conf.json / package.json / Cargo.toml
 *   4. 在 src/version-notes.json 顶部追加新版本条目（notes 留空，
 *      请在下次打包前手动补充该版本的更新说明）
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

const TAURI_CONF = join(ROOT, "src-tauri", "tauri.conf.json");
const PKG = join(ROOT, "package.json");
const CARGO = join(ROOT, "src-tauri", "Cargo.toml");
const NOTES = join(ROOT, "src", "version-notes.json");

function bumpPatch(version) {
  const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
  if (!m) {
    throw new Error(`版本号格式不合法（应为 x.y.z）: ${version}`);
  }
  const [, major, minor, patch] = m;
  return `${major}.${minor}.${Number(patch) + 1}`;
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf-8"));
}

function writeJson(path, data) {
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n", "utf-8");
}

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// 1. 读取当前版本并递增
const conf = readJson(TAURI_CONF);
const current = conf.version;
const next = bumpPatch(current);

// 2. 同步三处版本号
conf.version = next;
writeJson(TAURI_CONF, conf);

const pkg = readJson(PKG);
pkg.version = next;
writeJson(PKG, pkg);

const cargo = readFileSync(CARGO, "utf-8");
const cargoNext = cargo.replace(
  /^(\[package\][^\[]*?version\s*=\s*)"[^"]+"/m,
  `$1"${next}"`
);
if (cargoNext === cargo && !cargo.includes(`version = "${next}"`)) {
  throw new Error(`Cargo.toml 中未找到 [package] version 字段`);
}
writeFileSync(CARGO, cargoNext, "utf-8");

// 3. 追加版本说明条目（已存在则跳过）
const notes = readJson(NOTES);
if (!Array.isArray(notes) || notes.some((n) => n.version === next)) {
  writeJson(NOTES, notes);
} else {
  notes.unshift({ version: next, date: today(), notes: [] });
  writeJson(NOTES, notes);
}

console.log(`版本已递增: ${current} -> ${next}`);
console.log(`请在下次打包前补充 src/version-notes.json 中 ${next} 的更新说明`);
