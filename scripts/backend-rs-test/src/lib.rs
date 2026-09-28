//! 让 `src-tauri/src/backend.rs` 能脱离 tauri 单独跑测试。
//!
//! 为什么单独开一个 crate：`src-tauri` 依赖整棵 tauri 依赖树（几百个 crate、
//! 首次编译要下载上百 MB）。而 `backend.rs` 本身**只依赖 std**——把它 include
//! 进来，就能在几秒内验证进程管理逻辑，不用等 tauri 编译完。
//!
//! 这里用 `#[path]` 直接引用源文件，而不是复制一份：复制出来的副本迟早会和
//! 实现漂移，那时候测试通过反而更危险。
//!
//! 跑法：
//!   cargo test --manifest-path scripts/backend-rs-test/Cargo.toml

#[path = "../../../src-tauri/src/backend.rs"]
pub mod backend;
