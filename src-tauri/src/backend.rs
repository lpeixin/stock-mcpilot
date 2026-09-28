//! 打包后的后端进程管理。
//!
//! 策略（与用户确认过的口径一致）：
//!   - **开发时手动**：`tauri dev` 不该替开发者决定用哪个 Python 环境，所以
//!     debug 构建下不自动拉起后端，只探测 + 提示。
//!   - **打包后自动**：release 构建下若 8000 端口上没有健康的后端，就拉起
//!     sidecar，并在窗口关闭时把它收干净。
//!
//! 这个模块**只依赖 std**，刻意不引入 tauri 或 HTTP 客户端：这样它可以被
//! 单独编译测试（见文件末尾的 tests），而不是只能靠"跑一遍整个 App"来验证。
//! 探测健康用的是一个手写的最小 HTTP 请求，为此拉一个 HTTP 库不值得。

// `resolve_backend` / `choose_port` / `ensure` 只在 **release** 构建里被 main.rs
// 用到（开发模式不自动拉起后端），所以 debug 构建下它们必然显示为 dead_code。
// 这是设计使然，不是遗漏。注意只对 debug 放宽 —— release 下仍会正常检查。
#![cfg_attr(debug_assertions, allow(dead_code))]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
pub const DEFAULT_HOST: &str = "127.0.0.1";
pub const DEFAULT_PORT: u16 = 8000;

/// sidecar 可执行文件名。Tauri 打包时会在文件名后追加 target triple，
/// 但落到 app bundle 里时会去掉，所以运行时找的就是这个名字。
const SIDECAR_NAME: &str = "stock-mcpilot-server";

/// 等后端就绪的上限。首次启动要 import pandas / yfinance，冷启动确实慢。
const READY_TIMEOUT: Duration = Duration::from_secs(90);

/// 单次健康探测的超时。
const PROBE_TIMEOUT: Duration = Duration::from_millis(600);

/// `choose_port` 最多往后试几个端口。
const PORT_SCAN: u16 = 8;

// --------------------------------------------------------------------------
// 探测
// --------------------------------------------------------------------------

fn address_of(port: u16) -> Option<SocketAddr> {
    format!("{DEFAULT_HOST}:{port}").parse().ok()
}

/// 端口上的状况。
#[derive(Debug, PartialEq, Eq)]
enum PortState {
    /// 没人监听，可以用。
    Free,
    /// 是我们的后端在跑，可以复用。
    Ours,
    /// 有东西在监听，但不是我们的后端。不能硬上（会绑定失败），
    /// 也不能当成自己的用（前端会拿到一堆 404）。
    Foreign,
}

/// **一次连接**同时判断"有没有人监听"和"是不是我们的后端"。
///
/// 刻意不做成"先 connect 探测、再 connect 发 HTTP"两步：那是两次连接，
/// 中间目标可能刚好在重启/换绑，两次结果不一致时会得出自相矛盾的结论
/// （实测某些监听实现在处理完一个连接后会有短暂的监听空窗，两步探测
/// 会稳定地踩中它）。
fn inspect_port(port: u16) -> PortState {
    let address = match address_of(port) {
        Some(value) => value,
        None => return PortState::Foreign, // 端口号非法，当作不可用
    };
    let mut stream = match TcpStream::connect_timeout(&address, PROBE_TIMEOUT) {
        Ok(value) => value,
        Err(_) => return PortState::Free,
    };
    let _ = stream.set_read_timeout(Some(PROBE_TIMEOUT));
    let _ = stream.set_write_timeout(Some(PROBE_TIMEOUT));

    let request = format!(
        "GET /health HTTP/1.0\r\nHost: {DEFAULT_HOST}:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return PortState::Foreign;
    }

    let mut response = String::new();
    // 对端不实现 HTTP 时读会超时报错，response 为空 —— 那正是 Foreign
    let _ = stream.read_to_string(&mut response);
    if response.contains("\"status\"") && response.contains("ok") {
        PortState::Ours
    } else {
        PortState::Foreign
    }
}

/// 用最小 HTTP 请求确认端口上跑的是**我们的**后端，而不只是"有东西在监听"。
///
/// 只做 TCP connect 是不够的：8000 上完全可能是别的服务，那样前端会拿到一堆
/// 莫名其妙的 404。
pub fn probe_health(port: u16) -> bool {
    inspect_port(port) == PortState::Ours
}

/// 挑一个可以用的端口。
///
/// 从 `preferred` 开始往后扫最多 `PORT_SCAN` 个：我们的后端在上面就复用它，
/// 空着就用它，被别人占着就让开。全都被占就返回 `None`，交给调用方报错。
pub fn choose_port(preferred: u16) -> Option<u16> {
    for offset in 0..PORT_SCAN {
        let port = preferred.checked_add(offset)?;
        match inspect_port(port) {
            PortState::Ours | PortState::Free => return Some(port),
            PortState::Foreign => continue,
        }
    }
    None
}

// --------------------------------------------------------------------------
// 定位后端可执行文件
// --------------------------------------------------------------------------

/// 找一个能启动的后端。返回 `(可执行文件, 需要附加的参数)`。
///
/// 顺序：
///   1. `SMP_BACKEND_BIN` —— 显式覆盖，便于用系统 Python 调试打包产物；
///   2. 主程序同目录下的 sidecar —— 正常打包后的位置；
///   3. `SMP_BACKEND_PYTHON` + `SMP_BACKEND_CWD` —— 没打 sidecar 时的兜底，
///      直接跑源码（需要目标机器上有 Python 和依赖）。
pub fn resolve_backend() -> Option<(PathBuf, Vec<String>)> {
    if let Ok(raw) = std::env::var("SMP_BACKEND_BIN") {
        let candidate = PathBuf::from(raw.trim());
        if candidate.is_file() {
            return Some((candidate, Vec::new()));
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let name = if cfg!(windows) {
                format!("{SIDECAR_NAME}.exe")
            } else {
                SIDECAR_NAME.to_string()
            };
            let candidate = dir.join(name);
            if candidate.is_file() {
                return Some((candidate, Vec::new()));
            }
        }
    }

    if let Ok(python) = std::env::var("SMP_BACKEND_PYTHON") {
        let candidate = PathBuf::from(python.trim());
        if candidate.is_file() {
            let args = vec![
                "-m".to_string(),
                "uvicorn".to_string(),
                "backend.main:app".to_string(),
            ];
            return Some((candidate, args));
        }
    }

    None
}

// --------------------------------------------------------------------------
// 生命周期
// --------------------------------------------------------------------------

pub struct Backend {
    child: Mutex<Option<Child>>,
    port: u16,
    /// 端口上本来就有一个健康的后端（用户自己起的）。
    /// 这种情况下我们**不拥有**它，退出时也不能杀。
    external: bool,
}

impl Backend {
    /// 复用已经在跑的后端（例如 `tauri dev` 时开发者自己起的那个）。
    ///
    /// 不拥有、不探测、退出时不杀 —— 调用方负责先确认它真的健康。
    pub fn external(port: u16) -> Self {
        Self {
            child: Mutex::new(None),
            port,
            external: true,
        }
    }

    /// 确保有一个可用的后端：已有就复用，没有就拉起并等它就绪。
    pub fn ensure(port: u16) -> Result<Self, String> {
        if probe_health(port) {
            return Ok(Self::external(port));
        }

        let (binary, extra_args) = resolve_backend().ok_or_else(|| {
            format!(
                "没有找到后端可执行文件（{SIDECAR_NAME}）。\
                 开发时请手动启动：.venv/bin/python -m uvicorn backend.main:app --host {DEFAULT_HOST} --port {port}"
            )
        })?;

        let mut command = Command::new(&binary);
        command
            .args(&extra_args)
            .arg("--host")
            .arg(DEFAULT_HOST)
            .arg("--port")
            .arg(port.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        if let Ok(cwd) = std::env::var("SMP_BACKEND_CWD") {
            command.current_dir(cwd);
        }

        // 让子进程自成进程组。PyInstaller 的 onefile 引导器会 fork 出真正的
        // Python 进程，只 kill 父进程会留下占着 8000 端口的孤儿 —— 下次启动
        // 就会撞上"端口已被占用"，而且用户完全看不到是谁占的。
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let child = command
            .spawn()
            .map_err(|error| format!("启动后端失败（{}）：{error}", binary.display()))?;

        let handle = Self {
            child: Mutex::new(Some(child)),
            port,
            external: false,
        };

        let deadline = Instant::now() + READY_TIMEOUT;
        while Instant::now() < deadline {
            if probe_health(port) {
                return Ok(handle);
            }
            std::thread::sleep(Duration::from_millis(300));
        }

        // 就绪失败也要收掉进程，否则会留下一个半死不活的后端
        handle.shutdown();
        Err(format!(
            "后端在 {} 秒内没有就绪，请检查依赖是否完整。",
            READY_TIMEOUT.as_secs()
        ))
    }

    pub fn base_url(&self) -> String {
        format!("http://{DEFAULT_HOST}:{}", self.port)
    }

    /// 是否是复用外部已有的后端（此时不负责收尾）。
    pub fn is_external(&self) -> bool {
        self.external
    }

    pub fn shutdown(&self) {
        if self.external {
            return;
        }
        let mut guard = match self.child.lock() {
            Ok(value) => value,
            Err(poisoned) => poisoned.into_inner(),
        };
        if let Some(mut child) = guard.take() {
            terminate_tree(&mut child);
        }
    }
}

impl Drop for Backend {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// 结束整个进程组，先礼后兵。
#[cfg(unix)]
fn terminate_tree(child: &mut Child) {
    let pid = child.id();
    // 负 PID 表示"整个进程组"。用 /bin/kill 而不是 libc，是为了让这个模块
    // 保持零依赖、可单独编译测试。
    let _ = Command::new("/bin/kill")
        .arg("-TERM")
        .arg(format!("-{pid}"))
        .status();

    for _ in 0..25 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    let _ = Command::new("/bin/kill")
        .arg("-KILL")
        .arg(format!("-{pid}"))
        .status();
    let _ = child.wait();
}

#[cfg(windows)]
fn terminate_tree(child: &mut Child) {
    let _ = Command::new("taskkill")
        .args(["/T", "/F", "/PID", &child.id().to_string()])
        .status();
    let _ = child.wait();
}

// --------------------------------------------------------------------------
// 测试
// --------------------------------------------------------------------------
//
// 这些测试可以脱离 tauri 单独跑（本模块只依赖 std）：
//   cargo test --manifest-path scripts/backend-rs-test/Cargo.toml

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::thread::JoinHandle;

    /// `resolve_backend` 读的是**进程级**环境变量，而 cargo test 默认并行跑。
    /// 两个测试都要动 `SMP_BACKEND_*`，不加锁就会互相把对方设的值删掉——
    /// 表现为随机失败，比直接失败难查得多。
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn env_guard() -> std::sync::MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    // ---- 通用小工具 ------------------------------------------------------

    /// 只做 TCP connect、不发请求。
    ///
    /// 用于"等端口起来"这类对协议无所谓的场合：走 `inspect_port` 的话每次
    /// 都要等 600ms 读超时，而这里只关心连接能不能建立。
    fn can_connect(port: u16) -> bool {
        match address_of(port) {
            Some(address) => TcpStream::connect_timeout(&address, PROBE_TIMEOUT).is_ok(),
            None => false,
        }
    }

    /// 等 `predicate` 成立，最多等 `tries` × 100ms。
    fn wait_until(tries: usize, mut predicate: impl FnMut() -> bool) -> bool {
        for _ in 0..tries {
            if predicate() {
                return true;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        predicate()
    }

    /// 进程是否还在。
    ///
    /// 用 `/bin/kill -0 <pid>`：0 号信号只做权限与存在性检查，不会真的发送
    /// 任何东西。刻意不用 `ps` —— 受限沙箱里 `ps` 会被安全策略拦掉，那时候
    /// `Command::output()` 仍返回 Ok 但 stdout 为空，测试会得出"进程已经死了"
    /// 的错误结论，比不测还糟。
    fn process_alive(pid: u32) -> bool {
        Command::new("/bin/kill")
            .arg("-0")
            .arg(pid.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|status| status.success())
            // kill 本身跑不起来时保守地认为还活着，避免虚假的安全感
            .unwrap_or(true)
    }

    // ---- 假服务：进程内的真 TCP 监听 --------------------------------------
    //
    // 这里**刻意不用 `nc`**。踩过的坑：`nc -k -l` 在每次处理完一个连接后会
    // 短暂关闭监听 socket，紧接着的下一次 connect 会失败。而 `inspect_port`
    // 的调用时序正好是"探测刚结束、马上再探测"，于是稳定地把一个**正在监听**
    // 的端口误判成"空闲"。真实服务器（uvicorn 等）有 accept backlog，不会有
    // 这个行为 —— 是替身不像，不是被测代码错。
    //
    // 换成进程内的 TcpListener 之后行为完全确定，而且能直接造出"我们的后端"
    // 与"别人的服务"两种对端，把 probe_health 的两条分支都测到。

    /// 一个回答固定内容的假 HTTP 服务。`body = None` 表示连上就关，
    /// 模拟"有东西在监听但不是 HTTP 服务"。
    struct FakeServer {
        stop: Arc<AtomicBool>,
        thread: Option<JoinHandle<()>>,
    }

    /// 我们的后端会返回的 /health 正文。
    const HEALTHY_BODY: &str = r#"{"status":"ok","version":"test"}"#;

    impl FakeServer {
        fn start(port: u16, body: Option<&'static str>) -> Self {
            let listener = TcpListener::bind((DEFAULT_HOST, port))
                .unwrap_or_else(|error| panic!("绑定 {port} 失败：{error}"));
            listener.set_nonblocking(true).unwrap();

            let stop = Arc::new(AtomicBool::new(false));
            let flag = Arc::clone(&stop);
            let thread = std::thread::spawn(move || {
                while !flag.load(Ordering::Relaxed) {
                    match listener.accept() {
                        Ok((mut stream, _)) => {
                            let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
                            let mut request = [0u8; 1024];
                            let _ = stream.read(&mut request);
                            if let Some(body) = body {
                                let response = format!(
                                    "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\
                                     Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
                                    body.len()
                                );
                                let _ = stream.write_all(response.as_bytes());
                                let _ = stream.flush();
                            }
                            // body 为 None 时直接落到 drop，客户端读到 EOF
                        }
                        Err(ref error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(5));
                        }
                        Err(_) => break,
                    }
                }
            });

            let server = Self {
                stop,
                thread: Some(thread),
            };
            assert!(
                wait_until(40, || can_connect(port)),
                "假服务没能在 {port} 上监听"
            );
            server
        }

        /// 一个"是我们的后端"的假服务。
        fn healthy(port: u16) -> Self {
            Self::start(port, Some(HEALTHY_BODY))
        }

        /// 一个"别人的服务"的假服务。
        fn foreign(port: u16) -> Self {
            Self::start(port, None)
        }
    }

    impl Drop for FakeServer {
        fn drop(&mut self) {
            self.stop.store(true, Ordering::Relaxed);
            if let Some(thread) = self.thread.take() {
                let _ = thread.join();
            }
        }
    }

    // ---- 假后端进程：用于进程管理（terminate / shutdown）测试 -------------
    //
    // 这部分**必须**用真实子进程 —— 要验证的正是"能不能把别人的进程收干净"，
    // 进程内监听测不出这个。

    /// 测试用的假后端进程，`Drop` 里一定会清掉。
    ///
    /// 这一点不是洁癖：早期版本没有它，失败的运行在机器上留下了占着 8129 的
    /// nc，下一次运行于是以"shutdown 之后端口仍然被占用"这种完全误导人的
    /// 方式挂掉，白查了半天。
    struct FakeProcess {
        backend: Backend,
        pid: u32,
    }

    impl FakeProcess {
        fn spawn(port: u16) -> Self {
            let mut command = Command::new("/bin/sh");
            command
                .arg("-c")
                .arg(format!("exec /usr/bin/nc -k -l {DEFAULT_HOST} {port}"))
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            #[cfg(unix)]
            {
                use std::os::unix::process::CommandExt;
                command.process_group(0);
            }
            let child = command.spawn().expect("spawn nc");
            let pid = child.id();

            let process = Self {
                backend: Backend {
                    child: Mutex::new(Some(child)),
                    port,
                    external: false,
                },
                pid,
            };
            assert!(
                wait_until(40, || can_connect(port)),
                "假后端进程没能在 {port} 上监听"
            );
            process
        }

        /// 忽略 `external` 标记，强行把进程收掉，并且**要 `wait`** ——
        /// 只发信号的话会留下僵尸，而 `kill -0` 对僵尸仍然返回成功。
        fn force_kill(&self) {
            if let Ok(mut guard) = self.backend.child.lock() {
                if let Some(mut child) = guard.take() {
                    terminate_tree(&mut child);
                }
            }
        }
    }

    impl Drop for FakeProcess {
        fn drop(&mut self) {
            self.force_kill();
            let _ = wait_until(20, || !process_alive(self.pid));
        }
    }

    // ---- probe_health ----------------------------------------------------

    #[test]
    fn probe_rejects_closed_port() {
        // 9 号端口不会有服务监听
        assert!(!probe_health(9));
    }

    #[test]
    fn probe_rejects_plain_listener() {
        // 端口上"有东西在监听"不等于"是我们的后端"。这一条是 probe_health
        // 存在的全部理由：8000 上完全可能是别的服务。
        let _server = FakeServer::foreign(8131);
        assert!(can_connect(8131), "测试前提：端口确实被占着");
        assert!(!probe_health(8131), "非 HTTP 服务不该被认成后端");
        assert_eq!(inspect_port(8131), PortState::Foreign);
    }

    #[test]
    fn probe_accepts_our_backend() {
        let _server = FakeServer::healthy(8132);
        assert_eq!(inspect_port(8132), PortState::Ours);
        assert!(probe_health(8132));
    }

    #[test]
    fn probe_rejects_http_without_health_payload() {
        // 有 HTTP 服务、但 /health 不是我们的格式 —— 也不能认。
        // 光看"返回了 200"就认，等于把任何本机 web 服务都当成自己的后端。
        let _server = FakeServer::start(8133, Some("<html>hello</html>"));
        assert!(!probe_health(8133));
        assert_eq!(inspect_port(8133), PortState::Foreign);
    }

    // ---- choose_port -----------------------------------------------------

    #[test]
    fn choose_port_takes_free_port() {
        let port = 8142;
        assert!(!can_connect(port), "测试前提：端口 {port} 应该是空的");
        assert_eq!(choose_port(port), Some(port));
    }

    #[test]
    fn choose_port_skips_foreign_listener() {
        // 8000 被别的服务占着时，必须往后让，而不是硬上或假装它是我们的后端。
        let _server = FakeServer::foreign(8140);
        assert_eq!(choose_port(8140), Some(8141), "应该跳过被占的端口");
    }

    #[test]
    fn choose_port_reuses_our_backend() {
        // 已经有自己的后端在跑，就该复用它，而不是另起一个。
        let _server = FakeServer::healthy(8144);
        assert_eq!(choose_port(8144), Some(8144));
    }

    // ---- resolve_backend / ensure ----------------------------------------

    #[test]
    fn resolve_prefers_env_override() {
        let _guard = env_guard();
        let fake = std::env::temp_dir().join("smp-fake-backend");
        std::fs::write(&fake, b"#!/bin/sh\n").unwrap();
        std::env::set_var("SMP_BACKEND_BIN", fake.to_str().unwrap());
        let resolved = resolve_backend();
        std::env::remove_var("SMP_BACKEND_BIN");
        assert_eq!(resolved.map(|(path, _)| path), Some(fake));
    }

    #[test]
    fn ensure_reports_missing_binary_clearly() {
        let _guard = env_guard();
        std::env::remove_var("SMP_BACKEND_BIN");
        std::env::remove_var("SMP_BACKEND_PYTHON");
        // 用一个确定没人监听的端口，避免误判为"已有一个后端"
        match Backend::ensure(9) {
            Ok(_) => panic!("端口 9 上不该有健康的后端"),
            Err(message) => assert!(message.contains("没有找到后端可执行文件"), "{message}"),
        }
    }

    #[test]
    fn ensure_reuses_healthy_backend_without_owning_it() {
        // 复用分支：端口上已经有健康后端时，不该去找可执行文件、更不该另起一个。
        // 顺带断言 is_external —— 这决定退出时会不会把它带走。
        let _guard = env_guard();
        std::env::remove_var("SMP_BACKEND_BIN");
        std::env::remove_var("SMP_BACKEND_PYTHON");

        let _server = FakeServer::healthy(8146);
        let backend = Backend::ensure(8146).expect("应该复用已有后端");
        assert!(backend.is_external(), "复用的后端不该被当成自己拥有的");
        assert_eq!(backend.base_url(), format!("http://{DEFAULT_HOST}:8146"));
    }

    // ---- 进程生命周期 ----------------------------------------------------

    #[test]
    fn shutdown_terminates_owned_process() {
        // 确认 shutdown 之后进程真的没了、端口真的空出来。
        let port = 8129;
        let process = FakeProcess::spawn(port);

        process.backend.shutdown();

        // 先断言进程消失：这是权威判据。端口检查单看不够 —— nc 处理完连接后
        // 有短暂的监听空窗，会让"端口已空"偶发假成立。
        assert!(
            wait_until(40, || !process_alive(process.pid)),
            "shutdown 之后进程 {} 仍然活着",
            process.pid
        );
        assert!(!can_connect(port), "进程已退出，端口却仍然被占用");

        // shutdown 会把 child 取走；再调一次必须是幂等的空操作
        process.backend.shutdown();
    }

    #[test]
    fn shutdown_never_kills_external_backend() {
        // 复用用户自己起的后端时，我们**不拥有**它 —— 退出时绝不能顺手杀掉。
        // 这条契约一旦破了，用户的开发环境会被 App 关窗时带走。
        let port = 8130;
        let mut process = FakeProcess::spawn(port);
        process.backend.external = true;

        process.backend.shutdown();
        std::thread::sleep(Duration::from_millis(300));

        assert!(process_alive(process.pid), "外部后端被误杀了");
        assert!(can_connect(port), "外部后端的端口被误关了");
        // 收尾交给 FakeProcess::drop
    }

    #[test]
    fn external_constructor_owns_nothing() {
        // Backend::external 是"我看见了别人的后端，但它不是我的"。
        let backend = Backend::external(9999);
        assert!(backend.is_external());
        assert!(backend.child.lock().unwrap().is_none(), "不该持有任何子进程");
        // shutdown 必须是无操作（没有子进程可杀，也不能报错）
        backend.shutdown();
    }
}
