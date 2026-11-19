// ClipperLocal desktop shell.
// - starts the local Python engine (crews, video work, AI) and stops it on exit
// - the Browser window: one tab per account (own login profile, Italy box proxy). On Windows each tab
//   also gets a private DevTools port on 127.0.0.1 so the crew can work in the same signed-in tab.
// - listens for engine requests (e.g. "open this account tab") by polling the engine
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{
    LogicalPosition, LogicalSize, Manager, RunEvent, State, WebviewBuilder, WebviewUrl, WindowEvent,
};

const ENGINE_PORT: u16 = 8765;
const STRIP_H: f64 = 46.0;

#[derive(Clone, serde::Deserialize, Debug)]
#[allow(dead_code)]
struct Tab {
    key: String,
    upload_url: String,
    home_url: String,
    cdp_port: u16,
    proxy: String,
    profile: String,
}

struct AppState {
    root: Option<PathBuf>,
    engine: Mutex<Option<Child>>,
    active: Mutex<Option<String>>,
    created: Mutex<HashMap<String, String>>, // tab key -> webview label
}

// ------------------------------------------------------------------ engine process
fn find_root() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("CLIPPERLOCAL_ROOT") {
        return Some(PathBuf::from(p));
    }
    let mut starts = Vec::new();
    if let Ok(c) = std::env::current_dir() {
        starts.push(c);
    }
    if let Ok(e) = std::env::current_exe() {
        starts.push(e);
    }
    for s in starts {
        for dir in s.ancestors() {
            if dir.join("app").join("server.py").exists() {
                return Some(dir.to_path_buf());
            }
        }
    }
    None
}

fn python_path(root: &Path) -> PathBuf {
    let venv = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    if venv.exists() {
        venv
    } else if cfg!(windows) {
        PathBuf::from("python")
    } else {
        PathBuf::from("python3")
    }
}

fn port_open(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn start_engine(root: &Path) -> Option<Child> {
    if port_open(ENGINE_PORT) {
        return None;
    }
    let data = root.join("data");
    let _ = fs::create_dir_all(&data);
    let log = OpenOptions::new().create(true).append(true).open(data.join("engine.log")).ok();
    let mut cmd = Command::new(python_path(root));
    cmd.args(["-m", "app.server", "--no-browser"])
        .current_dir(root)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8");
    match log.and_then(|l| l.try_clone().ok().map(|c| (l, c))) {
        Some((out, err)) => {
            cmd.stdout(Stdio::from(out)).stderr(Stdio::from(err));
        }
        None => {
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // no console window
    }
    cmd.spawn().ok()
}

/// Minimal HTTP POST (empty body) to the local engine.
fn engine_post(path: &str) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], ENGINE_PORT).into();
    let Ok(mut s) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else { return false };
    let _ = s.set_read_timeout(Some(Duration::from_secs(5)));
    let ok = write!(s, "POST {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").is_ok();
    let mut buf = String::new();
    let _ = s.read_to_string(&mut buf);
    ok
}

/// Minimal HTTP GET to the local engine (no extra dependencies).
fn engine_get(path: &str) -> Option<String> {
    let addr: SocketAddr = ([127, 0, 0, 1], ENGINE_PORT).into();
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(500)).ok()?;
    s.set_read_timeout(Some(Duration::from_secs(5))).ok()?;
    write!(s, "GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").ok()?;
    let mut buf = String::new();
    s.read_to_string(&mut buf).ok()?;
    let body = buf.split_once("\r\n\r\n")?.1;
    Some(body.to_string())
}

fn engine_tabs() -> Vec<Tab> {
    engine_get("/api/tabs").and_then(|b| serde_json::from_str(&b).ok()).unwrap_or_default()
}

// ------------------------------------------------------------------ browser window
fn sanitize(s: &str) -> String {
    s.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect()
}

#[cfg(target_os = "macos")]
fn store_id(key: &str) -> [u8; 16] {
    let mut out = [0u8; 16];
    for half in 0..2u64 {
        let mut h: u64 = 0xcbf2_9ce4_8422_2325 ^ half;
        for b in key.bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x0100_0000_01b3);
        }
        out[(half as usize) * 8..(half as usize) * 8 + 8].copy_from_slice(&h.to_le_bytes());
    }
    out
}

fn browser_window(app: &tauri::AppHandle) -> Result<tauri::Window, String> {
    if let Some(w) = app.get_window("browser") {
        return Ok(w);
    }
    let w = tauri::window::WindowBuilder::new(app, "browser")
        .title("ClipperLocal · Accounts")
        .inner_size(1280.0, 900.0)
        .build()
        .map_err(|e| e.to_string())?;
    let size = w.inner_size().map_err(|e| e.to_string())?.to_logical::<f64>(w.scale_factor().unwrap_or(1.0));
    w.add_child(
        WebviewBuilder::new("tabstrip", WebviewUrl::App("tabs.html".into())),
        LogicalPosition::new(0.0, 0.0),
        LogicalSize::new(size.width, STRIP_H),
    )
    .map_err(|e| e.to_string())?;
    let handle = app.clone();
    w.on_window_event(move |ev| {
        if let WindowEvent::Resized(_) = ev {
            layout(&handle);
        }
        if let WindowEvent::Destroyed = ev {
            let st = handle.state::<AppState>();
            st.created.lock().unwrap().clear();
            *st.active.lock().unwrap() = None;
        }
    });
    Ok(w)
}

fn layout(app: &tauri::AppHandle) {
    let Some(w) = app.get_window("browser") else { return };
    let Ok(phys) = w.inner_size() else { return };
    let size = phys.to_logical::<f64>(w.scale_factor().unwrap_or(1.0));
    if let Some(strip) = app.get_webview("tabstrip") {
        let _ = strip.set_position(LogicalPosition::new(0.0, 0.0));
        let _ = strip.set_size(LogicalSize::new(size.width, STRIP_H));
    }
    let st = app.state::<AppState>();
    let active = st.active.lock().unwrap().clone();
    for (key, label) in st.created.lock().unwrap().iter() {
        if let Some(v) = app.get_webview(label) {
            if Some(key) == active.as_ref() {
                let _ = v.set_position(LogicalPosition::new(0.0, STRIP_H));
                let _ = v.set_size(LogicalSize::new(size.width, (size.height - STRIP_H).max(100.0)));
                let _ = v.show();
            } else {
                let _ = v.hide();
            }
        }
    }
}

fn ensure_tab(app: &tauri::AppHandle, tab: &Tab) -> Result<String, String> {
    let st = app.state::<AppState>();
    if let Some(label) = st.created.lock().unwrap().get(&tab.key) {
        return Ok(label.clone());
    }
    let w = browser_window(app)?;
    let label = format!("acct-{}", sanitize(&tab.key));
    let url: tauri::Url = tab.home_url.parse().map_err(|e| format!("bad url: {e}"))?;
    let profile = PathBuf::from(&tab.profile);
    fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
    let mut b = WebviewBuilder::new(&label, WebviewUrl::External(url)).data_directory(profile);
    #[cfg(windows)]
    {
        // Own DevTools port (127.0.0.1 only) so the crew can work in this exact tab, plus the account's proxy.
        let mut args = format!(
            "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection --remote-debugging-port={}",
            tab.cdp_port
        );
        if !tab.proxy.is_empty() {
            args.push_str(&format!(" --proxy-server={}", tab.proxy));
        }
        b = b.additional_browser_args(&args).user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
        );
    }
    #[cfg(target_os = "linux")]
    {
        if !tab.proxy.is_empty() {
            if let Ok(p) = tab.proxy.parse() {
                b = b.proxy_url(p);
            }
        }
    }
    #[cfg(target_os = "macos")]
    {
        b = b.data_store_identifier(store_id(&tab.key));
        if !tab.proxy.is_empty() {
            if let Ok(p) = tab.proxy.parse() {
                b = b.proxy_url(p); // needs macOS 14+
            }
        }
    }
    w.add_child(b, LogicalPosition::new(0.0, STRIP_H), LogicalSize::new(100.0, 100.0))
        .map_err(|e| e.to_string())?;
    st.created.lock().unwrap().insert(tab.key.clone(), label.clone());
    Ok(label)
}

fn show_tab(app: &tauri::AppHandle, key: Option<String>) -> Result<(), String> {
    let tabs = engine_tabs();
    if tabs.is_empty() {
        return Err("No accounts yet. Add them on the Channels page.".into());
    }
    let tab = match key {
        Some(k) => tabs.iter().find(|t| t.key == k).cloned().ok_or(format!("no tab {k}"))?,
        None => {
            let st = app.state::<AppState>();
            let cur = st.active.lock().unwrap().clone();
            cur.and_then(|k| tabs.iter().find(|t| t.key == k).cloned()).unwrap_or_else(|| tabs[0].clone())
        }
    };
    let w = browser_window(app)?;
    ensure_tab(app, &tab)?;
    *app.state::<AppState>().active.lock().unwrap() = Some(tab.key.clone());
    layout(app);
    let _ = w.show();
    let _ = w.unminimize();
    let _ = w.set_focus();
    Ok(())
}

// ------------------------------------------------------------------ commands
#[derive(serde::Serialize)]
struct EngineInfo {
    root: Option<String>,
    port: u16,
    running: bool,
}

#[tauri::command]
fn engine_info(state: State<AppState>) -> EngineInfo {
    EngineInfo {
        root: state.root.as_ref().map(|r| r.display().to_string()),
        port: ENGINE_PORT,
        running: port_open(ENGINE_PORT),
    }
}

#[tauri::command]
fn restart_engine(state: State<AppState>) -> Result<(), String> {
    let root = state.root.clone().ok_or("app folder not found")?;
    let mut guard = state.engine.lock().map_err(|e| e.to_string())?;
    match guard.take() {
        Some(mut c) => {
            let _ = c.kill();
            let _ = c.wait();
        }
        // engine not started by us (or it restarted itself): ask it to stop
        None => {
            engine_post("/api/shutdown");
        }
    }
    for _ in 0..20 {
        if !port_open(ENGINE_PORT) {
            break;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    *guard = start_engine(&root);
    Ok(())
}

#[tauri::command]
fn open_browser(app: tauri::AppHandle, tab: Option<String>) -> Result<(), String> {
    show_tab(&app, tab)
}

#[tauri::command]
fn switch_tab(app: tauri::AppHandle, key: String) -> Result<(), String> {
    show_tab(&app, Some(key))
}

#[tauri::command]
fn active_tab(state: State<AppState>) -> Option<String> {
    state.active.lock().unwrap().clone()
}

#[tauri::command]
fn tab_home(app: tauri::AppHandle, key: String) -> Result<(), String> {
    let tab = engine_tabs().into_iter().find(|t| t.key == key).ok_or("no such tab")?;
    let label = ensure_tab(&app, &tab)?;
    if let Some(v) = app.get_webview(&label) {
        let _ = v.navigate(tab.upload_url.parse().map_err(|e| format!("{e}"))?);
    }
    Ok(())
}

#[tauri::command]
fn reveal_file(path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    if !p.exists() {
        return Err(format!("{path} doesn't exist"));
    }
    let res = if cfg!(windows) {
        Command::new("explorer").arg(format!("/select,{}", p.display())).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg("-R").arg(&p).spawn()
    } else {
        Command::new("xdg-open").arg(if p.is_dir() { p.as_path() } else { p.parent().unwrap_or(&p) }).spawn()
    };
    res.map(|_| ()).map_err(|e| e.to_string())
}

#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err("only web links can be opened".into());
    }
    let res = if cfg!(windows) {
        Command::new("rundll32").args(["url.dll,FileProtocolHandler", &url]).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg(&url).spawn()
    } else {
        Command::new("xdg-open").arg(&url).spawn()
    };
    res.map(|_| ()).map_err(|e| e.to_string())
}

/// Engine -> app requests (the engine can't open windows itself).
fn poll_engine(app: tauri::AppHandle) {
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_millis(900));
        let Some(body) = engine_get("/api/app/commands") else { continue };
        let Ok(cmds) = serde_json::from_str::<Vec<serde_json::Value>>(&body) else { continue };
        for c in cmds {
            let h = app.clone();
            match c.get("cmd").and_then(|v| v.as_str()) {
                Some("open_browser") => {
                    let tab = c.get("tab").and_then(|v| v.as_str()).map(String::from);
                    let h2 = h.clone();
                    let _ = h.run_on_main_thread(move || {
                        let _ = show_tab(&h2, tab);
                    });
                }
                Some("reload_tabs") => {
                    let _ = h.emit_to("tabstrip", "reload", ());
                }
                _ => {}
            }
        }
    });
}

use tauri::Emitter;

fn main() {
    let root = find_root();
    let child = root.as_deref().and_then(start_engine);

    let app = tauri::Builder::default()
        .manage(AppState {
            root,
            engine: Mutex::new(child),
            active: Mutex::new(None),
            created: Mutex::new(HashMap::new()),
        })
        .invoke_handler(tauri::generate_handler![
            engine_info,
            restart_engine,
            open_browser,
            switch_tab,
            active_tab,
            tab_home,
            reveal_file,
            open_external
        ])
        .setup(|app| {
            poll_engine(app.handle().clone());
            // Show the screens from the engine (read from disk), so changes the coding crew applies
            // appear without rebuilding the app. Until the engine answers, the built-in copy shows a loading state.
            let h = app.handle().clone();
            std::thread::spawn(move || {
                for _ in 0..240 {
                    if port_open(ENGINE_PORT) && engine_get("/api/health").is_some() {
                        if let Some(w) = h.get_webview_window("main") {
                            if let Ok(url) = format!("http://127.0.0.1:{ENGINE_PORT}/").parse() {
                                let _ = w.navigate(url);
                            }
                        }
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(500));
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start ClipperLocal");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let state = handle.state::<AppState>();
            let child = state.engine.lock().ok().and_then(|mut g| g.take());
            if let Some(mut c) = child {
                let _ = c.kill();
                let _ = c.wait();
            } else {
                engine_post("/api/shutdown");
            }
        }
    });
}
