# 🎴 UNO Online (Streamlit)

Multiplayer UNO you can play with friends over a shared link. Pick **2–8 players**, fill empty
seats with bots, and everyone joins the same room from their own browser.

## Files
| File | Purpose |
|---|---|
| `streamlit_app.py` | The UI (lobby, table, hand, controls) |
| `uno_core.py` | Rules engine — deck, turns, stacking, UNO penalties, bot AI |
| `store.py` | SQLite room store so all browsers share one game state |
| `host_game.py` | One-command launcher: venv + server + public link |
| `START_UNO_SERVER.bat` | Double-click launcher for Windows |
| `start_uno_server.sh` | Launcher for WSL / Linux / macOS |
| `requirements.txt` | Dependencies (just Streamlit) |

## Quick start — host from your laptop

**Windows:** double-click **`START_UNO_SERVER.bat`**
**WSL / Linux / macOS:** `./start_uno_server.sh`

That one step creates the venv, installs Streamlit, starts the server, opens a public
link, and keeps the laptop awake. Share the printed link. Ctrl+C (or closing the window)
stops everything.

```
  SERVER IS LIVE — your laptop is now the host
  Share this link with friends (anywhere):
     https://pale-rider-moves.trycloudflare.com
  Same WiFi:  http://192.168.1.14:8501
```

Options: `--lan-only` (skip the public link), `--port 8600` (different port).

## Run manually
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on WSL/Linux
pip install -r requirements.txt
streamlit run streamlit_app.py
```
Opens at `http://localhost:8501`. Friends on the **same Wi-Fi** can use the Network URL that
Streamlit prints. For friends elsewhere, deploy it (below) or tunnel it.

## Deploy to Streamlit Community Cloud (always-on link)

1. Push this folder to a **GitHub repo** (public, or private — private works, but the free tier
   allows only one private app at a time).
2. Go to **share.streamlit.io** → **Create app** → *"Yup, I have an app"*.
3. Repo + branch `main` + entrypoint **`streamlit_app.py`**. Pick a subdomain, e.g.
   `aditya-uno` → `https://aditya-uno.streamlit.app`.
4. Advanced settings → Python **3.12**. No secrets needed.
5. Deploy. First build takes a couple of minutes.

Share `https://your-app.streamlit.app` and friends join with the 4-letter room code.

**Two things to know:**
- Apps sleep after **12 hours with no traffic**. The first visitor sees a "wake up" button and
  waits ~30s. Git commits no longer wake an app.
- The container's disk is ephemeral. A sleep, restart, or redeploy **clears active rooms**.
  Finish a game in one sitting; start a fresh room next time.

`.gitignore` already excludes the venv, the 35 MB tunnel binary, and `uno_rooms.db`.

## Other free hosting
**Streamlit Community Cloud — recommended**
1. Push these files to a public GitHub repo.
2. Go to `share.streamlit.io` → **New app** → pick the repo → main file `streamlit_app.py` → Deploy.
3. You get a URL like `https://your-app.streamlit.app`. Create a room, then share
   `https://your-app.streamlit.app/?room=ABCD` — the code is already in the link.

**Quick alternative (no deploy):** run locally and expose the port with a tunnel, e.g.
`cloudflared tunnel --url http://localhost:8501` or `ngrok http 8501`, then share the printed URL.

## How to play
1. **Create a room** → enter your name, choose the number of players, tweak house rules.
2. Share the URL or the 4-letter code. Friends open **Join a room**, type their name, hit Join.
3. Host clicks **Fill with bots** (optional) and **Start game**.
4. On your turn, playable cards light up — click one to play it. Wilds ask for a colour.
   Otherwise hit **Draw a card**.
5. Tick **Call UNO** *before* playing your second-last card, or opponents can **catch** you for +2.
6. First to empty their hand wins. The host can start another round with the same players.

## House rules (set at room creation)
- **Stacking** — answer a +2 with a +2, or a +4 with a +4, passing the pile on.
- **Draw until playable** — keep drawing until you can play, instead of a single card.
- **UNO catch penalty** — +2 cards if someone catches you on one card without calling UNO.
- **Hand size** — 5 to 10 cards.

## Notes
- The board polls every ~2 seconds (**Auto-refresh** toggle in the sidebar) so you see other
  players' moves. Turn it off if you prefer manual **Refresh**.
- Rooms live in `uno_rooms.db` next to the app and auto-expire after 12 hours. On Streamlit Cloud
  the filesystem is ephemeral, so a redeploy or container restart clears active rooms — fine for a
  game night, not meant for long-term stats.
- If two people click at the exact same instant, the later write wins; a refresh resyncs everyone.
- Implements the standard 108-card deck. Wild +4 challenges are not implemented; if the deck runs
  out with no legal moves left, the player with the fewest cards takes the round.
