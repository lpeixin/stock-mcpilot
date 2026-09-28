//! Tauri 桌面壳。
//!
//! 职责很窄：把窗口开起来，并把 Python 后端**按约定**带起来。
//! 后端的进程管理全部在 `backend` 模块里（那个模块只依赖 std，可以脱离 tauri
//! 单独测试：`cargo test --manifest-path scripts/backend-rs-test/Cargo.toml`）。
//!
//! 启动策略（与用户确认过的口径一致）：
//!   - **开发时手动**：`tauri dev` 不自动拉起后端。开发者手上有 venv、conda、
//!     系统 Python 好几套，壳不该替人挑；只探测 + 给出确切的手动启动命令。
//!   - **打包后自动**：release 构建下若端口上没有健康的后端，就拉起 sidecar，
//!     并在 App 退出时把它连同整个进程组收干净。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;

use std::sync::Mutex;

use tauri::{Manager, RunEvent};

/// 后端句柄。交给 tauri 托管，App 退出时随托管状态一起析构。
///
/// 用 `Option` 包一层是因为后端是**异步**就绪的（见 `setup` 里的线程）：
/// 窗口出现时后端可能还没起来，命令要能返回"还没有"而不是阻塞。
#[derive(Default)]
struct BackendState(Mutex<Option<backend::Backend>>);

impl BackendState {
    fn set(&self, backend: backend::Backend) {
        let mut guard = self.lock();
        // 理论上不会发生；真发生了也不能把旧的直接丢掉 —— 那是我们拥有的进程，
        // 丢掉引用就等于泄漏一个占着端口的孤儿。先收掉再放新的。
        if let Some(previous) = guard.replace(backend) {
            previous.shutdown();
        }
    }

    fn take(&self) -> Option<backend::Backend> {
        self.lock().take()
    }

    fn base_url(&self) -> Option<String> {
        self.lock().as_ref().map(|backend| backend.base_url())
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Option<backend::Backend>> {
        // 锁中毒说明某个线程在持锁时 panic 了。这里的临界区只有几次赋值，
        // 状态依然自洽，恢复比直接 panic 更合理。
        self.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

/// 告诉前端后端实际监听的地址。
///
/// 前端不该硬编码端口：8000 被别的服务占用时后端会顺延到 8001、8002……，
/// 那时界面会显示"无法连接后端"，而后端其实好好跑着。
#[tauri::command]
fn backend_base_url(state: tauri::State<'_, BackendState>) -> Option<String> {
    state.base_url()
}

/// 按「开发手动 / 生产自动」的约定取得一个可用的后端。
fn acquire_backend() -> Result<backend::Backend, String> {
    #[cfg(debug_assertions)]
    {
        let port = backend::DEFAULT_PORT;
        if backend::probe_health(port) {
            // 开发者自己起的后端：我们只是看见了它，不拥有、退出时也不动它。
            return Ok(backend::Backend::external(port));
        }
        Err(format!(
            "未检测到后端（http://{}:{}）。\n\
             开发模式不会自动拉起后端，请手动启动：\n  \
             .venv/bin/python -m uvicorn backend.main:app --host {} --port {}",
            backend::DEFAULT_HOST,
            port,
            backend::DEFAULT_HOST,
            port,
        ))
    }

    #[cfg(not(debug_assertions))]
    {
        let port = backend::choose_port(backend::DEFAULT_PORT).ok_or_else(|| {
            format!(
                "从端口 {} 起连续若干个端口都被别的服务占用，找不到可用端口。",
                backend::DEFAULT_PORT
            )
        })?;
        backend::Backend::ensure(port)
    }
}

fn main() {
    tauri::Builder::default()
        // 新闻条目要能用系统默认浏览器打开原文。Tauri v2 里没有 v1 的
        // `shell-open` 特性，这件事由 opener 插件负责；对应权限在
        // capabilities/default.json 里（opener:default 已覆盖 http/https）。
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend_base_url])
        .setup(|app| {
            app.manage(BackendState::default());

            let handle = app.handle().clone();
            // 冷启动要 import pandas / yfinance，实测要十几秒。放在 setup 里同步
            // 做的话窗口会迟迟不出现，用户看到的是"双击了没反应"。所以丢到后台
            // 线程：窗口立刻出来，前端自己轮询 /health，并通过 backend_base_url
            // 拿到实际端口。
            std::thread::spawn(move || match acquire_backend() {
                Ok(backend) => {
                    let url = backend.base_url();
                    let reused = backend.is_external();
                    if let Some(state) = handle.try_state::<BackendState>() {
                        state.set(backend);
                    }
                    eprintln!(
                        "[stock-mcpilot] 后端就绪：{url}{}",
                        if reused { "（复用已有进程）" } else { "" }
                    );
                }
                // 后端起不来不该让整个 App 崩掉：窗口照常开，界面会显示
                // 离线提示与手动启动命令，这比一个白屏或闪退有用得多。
                Err(message) => eprintln!("[stock-mcpilot] {message}"),
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                // 显式收尾：托管的 state 在进程退出时也会析构，但那个时机不受
                // 我们控制。退出路径上多写一行，能保证 sidecar 一定被带走。
                if let Some(state) = app.try_state::<BackendState>() {
                    if let Some(backend) = state.take() {
                        backend.shutdown();
                    }
                }
            }
        });
}
