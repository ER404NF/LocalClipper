# The Italy box

An old laptop in Turin that stays plugged in on the housing-complex LAN. Every account tab
and the Android phone send their traffic through it, so TikTok, YouTube and Instagram always see
the accounts being used from Italy, where they were made and where the money gets paid out.

## How it works
- **Tailscale** joins the laptop, your brother's PC and the phone into one private network.
  Nothing is opened to the internet. No port forwarding, and the housing router needs no changes.
- The **phone** uses the laptop as a Tailscale *exit node*, so all phone traffic comes out in Italy.
- The **account tabs** in ClipperLocal use a small SOCKS5 proxy on the laptop. It only listens on
  the Tailscale address, so nobody outside your Tailscale network can reach it.
- ClipperLocal checks the box before every post. If the traffic isn't coming out in Italy, the
  crew doesn't post. It pauses and tells your brother instead.

## Setup (about 10 minutes)
1. On the laptop (Windows), run **`ItalyBox-Setup.exe`** and click *Yes* when Windows asks for admin permission.
   (If Windows says *"Windows protected your PC"*: **More info → Run anyway**.)
2. It installs Tailscale and opens a browser: log in with **your** Tailscale account.
3. At the end it shows the Italy box address, like `socks5://100.x.y.z:1080`. Keep it.
4. In the Tailscale admin page (login.tailscale.com/admin/machines), open the laptop -> *Edit route settings*
   -> tick **Use as exit node**. Also turn off *key expiry* for the laptop, so it never logs out.
5. Invite your brother (*Users -> Invite*). The ClipperLocal installer already put Tailscale on his PC: he logs in from its tray icon.
6. On the **Android phone**: install Tailscale, log in, then *Exit node -> the laptop*. Also turn on
   *Settings -> Network -> VPN -> Always-on VPN* for Tailscale, so the phone never goes out directly.
7. In ClipperLocal: *Settings -> Italy box proxy* -> paste the address, then press **Check**. It should say `IT`.

No Python or other software is installed on the laptop: the proxy is one small program (`italybox-proxy.exe`)
that only listens on the Tailscale address, only accepts your own Tailscale devices, and refuses to reach the
housing LAN. To remove it: *Settings -> Apps -> ClipperLocal Italy box -> Uninstall*.
(Linux laptop instead: `sudo bash setup-italy-box.sh`.)

## Keep it healthy
- Leave it plugged in. The script turns off sleep, and closing the lid is fine.
- Windows Update can restart it. The proxy starts again by itself at boot.
- If the box goes offline, autopilot stops posting and nothing gets posted from Turkey by accident.
- Your friend's laptop only gets used as a network relay. Nothing else is stored on it.
