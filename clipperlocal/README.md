# ClipperLocal

A desktop app (Rust/Tauri) where a small **local AI crew** runs a GTA 6 clipping operation.
The crew finds streams, clips and edits shorts, and posts them to your TikTok, Instagram and
YouTube accounts. One local model (Qwen via Ollama) plays every role. Video work, the AI and the
accounts all stay on your own PC.

**Who owns what:** every account, campaign payout and monetization program is in the owner's
name (the person in Italy). The person running the PC (in Turkey) is the **manager**: he approves
plans, gives feedback and can stop anything at any time.

```
                    You (manager) ⇄ Agent
                          │ hands off
        ┌─────────────────┴──────────────────┐
  Production crew                      Coding crew
  Clipper A ⇄ Clipper B                Planner ⇄ Coder ⇄ Designer
  hunt · cross-review · edit           concept → approval → safe change
        │                                     │
        └──── shared brain (Obsidian-style notes in brain/) ────┘
                          │
   Account tabs (one signed-in browser per account) · Android phone (Edits)
                          │
                 Italy box (traffic exits in Turin)
```

## The crew
| Who | Job | Refuses |
|---|---|---|
| **Agent** | Talks to you, runs the day, the autopilot plan, reports | editing and coding (hands those off) |
| **Clipper A / B** | Hunt streams in parallel, review each other's clips, edit one clip each at the same time, post via tabs or the phone, research trends | coding |
| **Planner** | Turns your request into a plan + screen concepts for approval | clipping/posting |
| **Coder** | Makes the change on a separate copy, runs checks | clipping/posting |
| **Designer** | Draws concepts, reviews the result looks right | clipping/posting |

Everyone reads the shared **brain** (open `brain/` in Obsidian to see it). Each crew can only
write its own part. If you ask a clipper to change the app, it replies *"not my job"* and hands
the request to the coding crew.

## 1. Install (Windows, one time)
Needs about 40 GB free disk (most of it is the two AI models) and ideally an NVIDIA GPU with 8 GB+.

1. Run **`ClipperLocal-Setup.exe`**. If Windows says *"Windows protected your PC"*, click **More info → Run anyway**
   (the installer isn't code-signed, that's the only reason for the warning).
2. Click through. The installer sets up everything by itself: Python, video tools (ffmpeg), phone tools (adb), Git,
   the Ollama AI engine, WebView2 and the AI models. No Rust, no C++ tools, no winget, no command windows.
   Windows asks once for permission (firewall rule for the phone + Tailscale). Saying *No* is fine.
3. The first install takes 30-90 minutes, mostly downloading the AI models (~25 GB). The window shows progress.
   **If it stops** (internet drop, PC restart), just run the installer again: it skips what's done and resumes downloads.
4. Open **ClipperLocal** from the Desktop icon.

To update or repair later: run the newest `ClipperLocal-Setup.exe` again (Start menu → *Repair or update ClipperLocal*).
Your clips, logins, settings and the team's brain are kept. Installed to `%LOCALAPPDATA%\ClipperLocal`.

**AI models** (picked automatically for the PC; change them on the *AI models* page):
| Who | Model | Why |
|---|---|---|
| Agent + Clipper A/B | `qwen3.5:9b` | sees screenshots, uses tools, fits fully in an 8 GB GPU, two agents at once |
| Planner, Coder, Designer | `qwen3-coder:30b` | coding specialist; only ~3B of its 30B is active per word, so it runs from GPU + 32 GB RAM. Loads only when the coding crew works |

Mac/Linux developers: `./setup.sh` still works. To build the Windows installers from Linux: `installer/build_installer.sh`.

## 2. First-time setup in the app
1. **Settings → Italy box**: paste the address that `ItalyBox-Setup.exe` showed on the Turin laptop and press *Check* (see `italy-box/README.md`).
2. **Channels**: add each account (e.g. `tiktok:main`, `youtube:gta`). Pick a route for each one:
   *italy* (recommended), *direct*, or a custom proxy.
3. **Browser**: open each account's tab once and **log in yourself**. Each tab keeps its own
   cookies, like a separate browser profile, so the logins stay saved.
4. **Phone**: plug in the cheap Android, turn on *Developer options → USB debugging*, accept the prompt,
   install **Edits** and Instagram and log in. Then set up the phone's Tailscale exit node (Italy box README).
5. **config.yaml**: Twitch keys (free, dev.twitch.tv/console/apps) and the **streamers** whose clipping
   campaigns you joined, with each campaign's credit line. The crew only clips listed streamers.
6. **Models**: check that the team model is installed. Bigger models control the browser better if the GPU can fit them.

## 3. A normal day
- **Evening**: the Agent proposes tomorrow's plan on **Autopilot**: which clips, which account, what time, how.
  You can change items, drop them, or approve the whole plan.
- **After approval**: wherever it can, the crew uses the platforms' own scheduler (TikTok Studio / YouTube Studio),
  so those posts go out even if the PC is off. For everything else it posts at the planned time through the
  account tab or the phone. The PC has to be on for those.
- **Any time**: open **Crew** to see what they're doing, give feedback on a clip ("hook too slow"),
  press **Pause all**, or take over a tab yourself.
- **22:15**: a **Report** shows what was posted, what failed and how the numbers moved.
- **Money** tracks campaign views and monetization progress (TikTok 10K followers / 100K views in 30d;
  YouTube 1,000 subs + 10M Shorts views in 90d).

## Asking the coding crew about the app
In **Coding crew**, ask anything about how the app works, e.g. *"can the production crew post to two accounts at once?"*.
The Coder reads the app's real code before answering (it is made to check the code first), and names the file and line
it found the answer in, like `app/crew.py:97`. If the code can't do it, it says so and offers to build it.

## Changing the app while it's open
1. Describe the change in **Coding crew**. The Planner plans it; for screen changes the Designer shows concepts to pick from.
2. The Coder builds it on a **separate copy** of the app and runs checks. Your app keeps running normally.
3. Press **Preview live**: the changed app opens inside the review window (with a copy of today's data) so you can click around.
4. Press **Apply & save**: the change is saved as a new version. Screen-only changes appear instantly;
   engine changes restart the engine by itself (~5 seconds). **Undo** puts the old version back the same way.

## Safety rules built in
- No posting if the Italy box is offline or the traffic isn't coming out in Italy.
- Limits on posts per account per day and minutes between posts. Posting only happens inside the window.
- Tabs and the phone only go to the platform sites they need. The agents work with a goal and
  page hints, not by scrolling around.
- The engine only listens on `127.0.0.1` and refuses commands coming from websites (only the app's own screens can
  control it). The phone share server only serves single files behind a random token.
- Coding crew changes go onto a separate git branch, get checked, and only go live after **you press Apply**.
  **Undo** reverts a change in one click. The crew can only touch `app/` and `desktop/ui/`.

## Honest status
What has been tested and what still needs a real run on the Windows PC:
- **Tested**: the engine, the crew hand-offs and job refusals, the brain, the coding crew's
  worktree → checks → apply → undo, video rendering (all layouts + platform safe areas),
  the browser agent uploading and scheduling on mock upload pages, and every UI page.
- **Needs a real run**:
  - how well the real Qwen model uses the tools (tested here with a scripted stand-in)
  - the Windows build and the in-app tab control (WebView2). Some of this was checked by reading the code only.
  - the real TikTok, YouTube and Instagram/Edits screens. These sites change, so expect to tune `app/playbooks.py`.
  - Whisper captions and the Italy box
- Expect a first week of supervision: watch the crew post a few times before trusting autopilot.

## Rules of the game
Only clip streamers whose campaigns you joined and follow each campaign's rules (credit lines, allowed platforms).
Re-uploaded clips can be flagged as *unoriginal* for monetization, so the edits (hooks, captions, split-screen,
commentary) are what make them count. Keep each account consistent: same country, same device, human pace.
