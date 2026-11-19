//! ClipperLocal Italy box proxy: a minimal SOCKS5 server (CONNECT, no auth) with no dependencies.
//! Safety: it only listens on the Tailscale address (100.x.y.z) and only accepts clients from the
//! Tailscale range 100.64.0.0/10, so nothing on the internet or the housing LAN can use it.
//! Usage: italybox-proxy [--listen 100.x.y.z:1080] [--any-client]
//! Without --listen it asks Tailscale for this machine's address (and waits until Tailscale is up).
use std::io::{self, Read, Write};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, Shutdown, SocketAddr, TcpListener, TcpStream, ToSocketAddrs};
use std::process::Command;
use std::thread;
use std::time::Duration;

fn tailscale_ip() -> Option<Ipv4Addr> {
    let candidates = [
        "tailscale".to_string(),
        r"C:\Program Files\Tailscale\tailscale.exe".to_string(),
    ];
    for exe in candidates {
        let mut cmd = Command::new(&exe);
        cmd.args(["ip", "-4"]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000);
        }
        if let Ok(out) = cmd.output() {
            let text = String::from_utf8_lossy(&out.stdout);
            if let Some(ip) = text.lines().filter_map(|l| l.trim().parse::<Ipv4Addr>().ok()).next() {
                return Some(ip);
            }
        }
    }
    None
}

fn in_tailnet(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            let o = v4.octets();
            o[0] == 100 && (64..=127).contains(&o[1]) || v4.is_loopback()
        }
        IpAddr::V6(v6) => v6.is_loopback() || v6.segments()[0] == 0xfd7a, // Tailscale IPv6 range fd7a:115c:a1e0::/48
    }
}

static ALLOW_LAN: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn handshake(c: &mut TcpStream) -> io::Result<TcpStream> {
    let mut head = [0u8; 2];
    c.read_exact(&mut head)?;
    if head[0] != 5 {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "not SOCKS5"));
    }
    let mut methods = vec![0u8; head[1] as usize];
    c.read_exact(&mut methods)?;
    if !methods.contains(&0) {
        c.write_all(&[5, 0xff])?;
        return Err(io::Error::new(io::ErrorKind::InvalidData, "no-auth not offered"));
    }
    c.write_all(&[5, 0])?;
    let mut req = [0u8; 4];
    c.read_exact(&mut req)?;
    if req[1] != 1 {
        c.write_all(&[5, 7, 0, 1, 0, 0, 0, 0, 0, 0])?; // command not supported
        return Err(io::Error::new(io::ErrorKind::InvalidData, "only CONNECT"));
    }
    let host: String = match req[3] {
        1 => {
            let mut a = [0u8; 4];
            c.read_exact(&mut a)?;
            Ipv4Addr::from(a).to_string()
        }
        3 => {
            let mut len = [0u8; 1];
            c.read_exact(&mut len)?;
            let mut name = vec![0u8; len[0] as usize];
            c.read_exact(&mut name)?;
            String::from_utf8_lossy(&name).into_owned()
        }
        4 => {
            let mut a = [0u8; 16];
            c.read_exact(&mut a)?;
            format!("[{}]", Ipv6Addr::from(a))
        }
        _ => return Err(io::Error::new(io::ErrorKind::InvalidData, "bad address type")),
    };
    let mut port = [0u8; 2];
    c.read_exact(&mut port)?;
    let port = u16::from_be_bytes(port);
    let target = format!("{host}:{port}");
    let addrs: Vec<SocketAddr> = match target.to_socket_addrs() {
        Ok(a) => a.collect(),
        Err(e) => {
            c.write_all(&[5, 4, 0, 1, 0, 0, 0, 0, 0, 0])?; // host unreachable
            return Err(e);
        }
    };
    let mut last = io::Error::new(io::ErrorKind::Other, "no address");
    for a in addrs {
        // never relay into private networks (the housing LAN, this laptop) - internet only
        let private = match a.ip() {
            IpAddr::V4(v4) => v4.is_private() || v4.is_loopback() || v4.is_link_local() || in_tailnet(a.ip()),
            IpAddr::V6(v6) => v6.is_loopback() || (v6.segments()[0] & 0xfe00) == 0xfc00,
        };
        if private && !ALLOW_LAN.load(std::sync::atomic::Ordering::Relaxed) {
            last = io::Error::new(io::ErrorKind::PermissionDenied, "private address");
            continue;
        }
        match TcpStream::connect_timeout(&a, Duration::from_secs(15)) {
            Ok(up) => {
                c.write_all(&[5, 0, 0, 1, 0, 0, 0, 0, 0, 0])?;
                return Ok(up);
            }
            Err(e) => last = e,
        }
    }
    let code = if last.kind() == io::ErrorKind::PermissionDenied { 2 } else { 5 };
    let _ = c.write_all(&[5, code, 0, 1, 0, 0, 0, 0, 0, 0]);
    Err(last)
}

fn pipe(mut from: TcpStream, mut to: TcpStream) {
    let _ = io::copy(&mut from, &mut to);
    let _ = to.shutdown(Shutdown::Write);
}

fn serve(mut c: TcpStream) {
    let _ = c.set_read_timeout(Some(Duration::from_secs(30)));
    let up = match handshake(&mut c) {
        Ok(u) => u,
        Err(_) => return,
    };
    let _ = c.set_read_timeout(None);
    let (c2, up2) = match (c.try_clone(), up.try_clone()) {
        (Ok(a), Ok(b)) => (a, b),
        _ => return,
    };
    let t = thread::spawn(move || pipe(c2, up2));
    pipe(up, c);
    let _ = t.join();
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let any_client = args.iter().any(|a| a == "--any-client");
    // --allow-lan: testing only (lets the proxy reach local addresses)
    ALLOW_LAN.store(args.iter().any(|a| a == "--allow-lan"), std::sync::atomic::Ordering::Relaxed);
    let listen: SocketAddr = match args.iter().position(|a| a == "--listen").and_then(|i| args.get(i + 1)) {
        Some(s) => s.parse().expect("--listen needs ip:port"),
        None => loop {
            if let Some(ip) = tailscale_ip() {
                break SocketAddr::new(IpAddr::V4(ip), 1080);
            }
            eprintln!("waiting for Tailscale to connect...");
            thread::sleep(Duration::from_secs(10));
        },
    };
    let listener = loop {
        match TcpListener::bind(listen) {
            Ok(l) => break l,
            Err(e) => {
                eprintln!("can't listen on {listen} yet ({e}), retrying");
                thread::sleep(Duration::from_secs(10));
            }
        }
    };
    println!("Italy box proxy on socks5://{listen}");
    for conn in listener.incoming().flatten() {
        let ok = conn.peer_addr().map(|p| any_client || in_tailnet(p.ip())).unwrap_or(false);
        if !ok {
            continue; // dropped: not from your Tailscale network
        }
        thread::spawn(move || serve(conn));
    }
}
