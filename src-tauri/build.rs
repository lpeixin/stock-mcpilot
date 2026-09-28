//! Tauri 构建脚本。
//!
//! 这个文件是必需的：`tauri::generate_context!()` 会去读 `OUT_DIR` 下的生成物，
//! 而 `OUT_DIR` 只有构建脚本才能提供。少了它编译会直接报
//! `OUT_DIR env var is not set, do you have a build script?`。
//!
//! 它同时负责把 `tauri.conf.json`、`capabilities/`、图标等打包期资源编译进来，
//! 所以改了这些文件之后需要重新构建（tauri-build 会自行声明重跑条件）。

fn main() {
    tauri_build::build()
}
