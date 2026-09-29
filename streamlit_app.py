"""UNO — online multiplayer, playable from a single shared link.

Run:  streamlit run streamlit_app.py
"""

from __future__ import annotations

import time

import streamlit as st

import store
import uno_core as uno

st.set_page_config(page_title="UNO Online", page_icon="🎴", layout="wide")
store.init()
store.prune()

COLOR_EMOJI = {"R": "🟥", "G": "🟩", "B": "🟦", "Y": "🟨", "W": "🌈"}

CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
div.stButton > button {width: 100%; border-radius: 10px; font-weight: 600;}
.unocard {
  display:inline-flex; flex-direction:column; align-items:center; justify-content:center;
  width:120px; height:170px; border-radius:16px; color:#fff; font-weight:800;
  box-shadow:0 8px 20px rgba(0,0,0,.28); border:6px solid #fff; text-align:center;
}
.unocard .big {font-size:44px; line-height:1.1;}
.unocard .small {font-size:13px; opacity:.9; letter-spacing:.5px;}
.pill {display:inline-block; padding:4px 12px; border-radius:999px; color:#fff;
       font-weight:700; font-size:13px;}
.seat {padding:10px 14px; border-radius:12px; border:1px solid rgba(128,128,128,.35);
       margin-bottom:8px;}
.seat.turn {border:2px solid #f5a623; background:rgba(245,166,35,.12);}
.muted {opacity:.65; font-size:13px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Session / URL helpers
# --------------------------------------------------------------------------- #
def qp_get(key: str, default: str = "") -> str:
    try:
        return st.query_params.get(key, default) or default
    except Exception:
        return default


def qp_set(**kw) -> None:
    try:
        for k, v in kw.items():
            if v:
                st.query_params[k] = v
            elif k in st.query_params:
                del st.query_params[k]
    except Exception:
        pass


ss = st.session_state
ss.setdefault("room", qp_get("room").upper())
ss.setdefault("pid", qp_get("pid"))
ss.setdefault("wild_idx", None)
ss.setdefault("error", "")


def reload_state():
    return store.load(ss.room) if ss.room else None


def push(state) -> None:
    store.save(state)


def leave() -> None:
    ss.room, ss.pid, ss.wild_idx = "", "", None
    qp_set(room=None, pid=None)
    st.rerun()


def card_html(card: dict, color_override: str | None = None) -> str:
    c = color_override or card.get("chosen") or card["c"]
    bg = uno.COLOR_HEX.get(c, "#2b2b2b")
    if card["c"] == "W":
        label = "WILD" if card["v"] == "wild" else "+4"
        sub = f"colour: {uno.COLOR_NAMES.get(c, '—')}"
        inner = (f"<div class='big'>{label}</div><div class='small'>{sub}</div>"
                 if c != "W" else f"<div class='big'>{label}</div>")
        if c == "W":
            bg = "linear-gradient(135deg,#e4342a 0 25%,#e8b21a 25% 50%,#3aa63a 50% 75%,#1f7ae0 75%)"
            return f"<div class='unocard' style='background:{bg}'>{inner}</div>"
        return f"<div class='unocard' style='background:{bg}'>{inner}</div>"
    return (f"<div class='unocard' style='background:{bg}'>"
            f"<div class='big'>{uno.card_label(card)}</div>"
            f"<div class='small'>{uno.COLOR_NAMES[card['c']].upper()}</div></div>")


def btn_label(card: dict) -> str:
    return f"{COLOR_EMOJI[card['c']]} {uno.card_label(card)}"


# --------------------------------------------------------------------------- #
# Home: create / join
# --------------------------------------------------------------------------- #
def home() -> None:
    st.title("🎴 UNO Online")
    st.caption("Create a room, share the link, and play with up to 8 friends in the browser.")

    join_code = qp_get("room").upper()
    tab_join, tab_new = st.tabs(["🔗 Join a room", "➕ Create a room"])

    with tab_new:
        name = st.text_input("Your name", value="", max_chars=18, key="host_name",
                             placeholder="e.g. Aditya")
        n = st.slider("Number of players", uno.MIN_PLAYERS, uno.MAX_PLAYERS, 4,
                      help="Seats in the room. Empty seats can be filled with bots.")
        with st.expander("House rules"):
            stacking = st.checkbox("Allow stacking +2 on +2 and +4 on +4", value=True)
            draw_match = st.checkbox("Draw until you get a playable card", value=False)
            penalty = st.checkbox("UNO catch penalty (+2 cards)", value=True)
            hand_size = st.number_input("Starting hand size", 5, 10, 7)
        if st.button("Create room", type="primary", use_container_width=True):
            if not name.strip():
                st.warning("Enter your name first.")
            else:
                code = store.new_code()
                state = uno.new_game(code, n, name.strip(), {
                    "stacking": stacking, "draw_to_match": draw_match,
                    "uno_penalty": penalty, "hand_size": int(hand_size),
                })
                push(state)
                ss.room, ss.pid = code, state["players"][0]["id"]
                qp_set(room=code, pid=ss.pid)
                st.rerun()

    with tab_join:
        code = st.text_input("Room code", value=join_code, max_chars=6,
                             placeholder="ABCD").strip().upper()
        jname = st.text_input("Your name", max_chars=18, key="join_name",
                              placeholder="e.g. Rahul")
        if st.button("Join", type="primary", use_container_width=True):
            state = store.load(code)
            if not state:
                st.error("No room with that code. Ask the host to resend the link.")
            elif not jname.strip():
                st.warning("Enter your name first.")
            elif state["started"]:
                st.error("That game has already started.")
            else:
                pid = uno.add_player(state, jname.strip())
                if not pid:
                    st.error("Room is full.")
                else:
                    push(state)
                    ss.room, ss.pid = code, pid
                    qp_set(room=code, pid=pid)
                    st.rerun()


# --------------------------------------------------------------------------- #
# Lobby
# --------------------------------------------------------------------------- #
def lobby(state: dict) -> None:
    me = uno.player_by_id(state, ss.pid)
    is_host = bool(me) and state["players"][0]["id"] == ss.pid

    st.title(f"Room {state['room']}")
    st.caption("Share this page's URL (it already contains the room code) or just the 4-letter code.")
    st.code(f"?room={state['room']}", language=None)

    left, right = st.columns([3, 2])
    with left:
        st.subheader(f"Players ({len(state['players'])}/{state['num_players']})")
        for p in state["players"]:
            tag = " *(you)*" if p["id"] == ss.pid else ""
            tag += " 🤖" if p["is_bot"] else ""
            st.markdown(f"<div class='seat'>{p['name']}{tag}</div>", unsafe_allow_html=True)
        empty = state["num_players"] - len(state["players"])
        if empty:
            st.markdown(f"<span class='muted'>Waiting for {empty} more player(s)…</span>",
                        unsafe_allow_html=True)
    with right:
        r = state["rules"]
        st.subheader("House rules")
        st.write(f"- Stacking +2/+4: **{'on' if r['stacking'] else 'off'}**")
        st.write(f"- Draw until playable: **{'on' if r['draw_to_match'] else 'off'}**")
        st.write(f"- UNO catch penalty: **{'on' if r['uno_penalty'] else 'off'}**")
        st.write(f"- Hand size: **{r['hand_size']}**")

    c1, c2, c3, c4 = st.columns(4)
    if is_host:
        if c1.button("▶️ Start game", type="primary", disabled=len(state["players"]) < 2):
            uno.start_game(state)
            uno.run_bots(state)
            push(state)
            st.rerun()
        if c2.button("🤖 Fill with bots", disabled=not empty):
            uno.fill_with_bots(state)
            push(state)
            st.rerun()
    if c3.button("🔄 Refresh"):
        st.rerun()
    if c4.button("🚪 Leave"):
        if me:
            uno.remove_player(state, ss.pid)
            push(state) if state["players"] else store.delete(state["room"])
        leave()

    if not is_host:
        st.info("Waiting for the host to start the game.")
    auto_refresh(2)


# --------------------------------------------------------------------------- #
# Table
# --------------------------------------------------------------------------- #
def table(state: dict) -> None:
    me = uno.player_by_id(state, ss.pid)
    if not me:
        st.warning("You're not seated in this room.")
        if st.button("Back to home"):
            leave()
        return

    cur = uno.current_player(state)
    my_turn = (cur["id"] == me["id"]) and not state["finished"]

    head_l, head_r = st.columns([3, 1])
    head_l.title(f"UNO · Room {state['room']}")
    if head_r.button("🚪 Leave table"):
        leave()

    if state["finished"]:
        st.success(f"🏆 **{state['winner']}** wins!")

    board, side = st.columns([3, 2])

    # ---------------- board ---------------- #
    with board:
        top = uno.top_card(state)
        c_left, c_right = st.columns([1, 1])
        with c_left:
            st.markdown("**Top card**")
            st.markdown(card_html(top, state["active_color"]), unsafe_allow_html=True)
        with c_right:
            ac = state["active_color"] or "W"
            st.markdown("**Active colour**")
            st.markdown(
                f"<span class='pill' style='background:{uno.COLOR_HEX[ac]}'>"
                f"{uno.COLOR_NAMES[ac]}</span>", unsafe_allow_html=True)
            st.write("")
            st.write(f"Direction: {'➡️ clockwise' if state['direction'] == 1 else '⬅️ anti-clockwise'}")
            st.write(f"Draw pile: **{len(state['draw'])}** cards")
            if state["pending_draw"]:
                st.error(f"⚠️ Pending penalty: **+{state['pending_draw']}** "
                         f"({state['pending_kind']}) on {cur['name']}")

        st.divider()
        st.subheader("Turn order")
        for i, p in enumerate(state["players"]):
            cls = "seat turn" if i == state["current"] and not state["finished"] else "seat"
            you = " *(you)*" if p["id"] == me["id"] else ""
            bot = " 🤖" if p["is_bot"] else ""
            uno_flag = " 🔔 **UNO!**" if len(p["hand"]) == 1 and p["said_uno"] else ""
            st.markdown(
                f"<div class='{cls}'><b>{p['name']}</b>{you}{bot} — "
                f"{len(p['hand'])} card(s){uno_flag}</div>", unsafe_allow_html=True)
            if (state["rules"]["uno_penalty"] and not state["finished"]
                    and p["id"] != me["id"] and len(p["hand"]) == 1
                    and not p["said_uno"] and not p["caught"]):
                if st.button(f"👉 Catch {p['name']} (no UNO!)", key=f"catch_{p['id']}"):
                    msg = uno.catch_player(state, me["id"], p["id"])
                    push(state)
                    ss.error = msg
                    st.rerun()

    # ---------------- side log ---------------- #
    with side:
        st.subheader("Game log")
        st.markdown("\n".join(f"- {line}" for line in state["log"][:14]) or "_No moves yet._")

    st.divider()

    # ---------------- my hand ---------------- #
    st.subheader(f"Your hand — {len(me['hand'])} card(s)")
    if ss.error:
        st.warning(ss.error)
        ss.error = ""

    if state["finished"]:
        if state["players"][0]["id"] == me["id"]:
            if st.button("🔁 Play again (same players)", type="primary"):
                uno.restart_game(state)
                uno.run_bots(state)
                push(state)
                st.rerun()
        else:
            st.info("Waiting for the host to start a new round.")
        auto_refresh(3)
        return

    if not my_turn:
        st.info(f"⏳ Waiting for **{cur['name']}**…")

    playable = set(uno.playable_indices(state, me)) if my_turn else set()

    # Wild colour picker
    if ss.wild_idx is not None and my_turn:
        card = me["hand"][ss.wild_idx] if ss.wild_idx < len(me["hand"]) else None
        if card:
            st.markdown(f"**Choose a colour for your {uno.card_text(card)}:**")
            cols = st.columns(5)
            for j, col in enumerate(uno.COLORS):
                if cols[j].button(f"{COLOR_EMOJI[col]} {uno.COLOR_NAMES[col]}", key=f"wc_{col}"):
                    ss.error = uno.play_card(state, me["id"], ss.wild_idx, col,
                                             call_uno=ss.get("say_uno", False))
                    ss.wild_idx = None
                    if not ss.error:
                        uno.run_bots(state)
                    push(state)
                    st.rerun()
            if cols[4].button("✖️ Cancel", key="wc_cancel"):
                ss.wild_idx = None
                st.rerun()
        else:
            ss.wild_idx = None

    say_uno = st.checkbox("🔔 Call UNO with this play (tick before playing your second-last card)",
                          key="say_uno", value=False, disabled=len(me["hand"]) != 2)

    per_row = 8
    for start in range(0, len(me["hand"]), per_row):
        chunk = list(enumerate(me["hand"]))[start:start + per_row]
        cols = st.columns(per_row)
        for slot, (i, card) in enumerate(chunk):
            ok = i in playable
            with cols[slot]:
                if st.button(btn_label(card), key=f"card_{i}_{state['turn_no']}",
                             disabled=not ok, help=uno.card_text(card),
                             type="primary" if ok else "secondary"):
                    if card["c"] == "W":
                        ss.wild_idx = i
                        st.rerun()
                    ss.error = uno.play_card(state, me["id"], i, None, call_uno=say_uno)
                    if not ss.error:
                        uno.run_bots(state)
                    push(state)
                    st.rerun()

    st.write("")
    a, b, c, d = st.columns(4)
    draw_label = (f"🃏 Take +{state['pending_draw']}"
                  if state["pending_draw"] else "🃏 Draw a card")
    if a.button(draw_label, disabled=not my_turn, type="primary" if my_turn else "secondary"):
        ss.error = uno.draw_or_take(state, me["id"])
        if not ss.error:
            uno.run_bots(state)
        push(state)
        st.rerun()
    if b.button("⏭️ Pass", disabled=not my_turn, help="Only after you've drawn."):
        ss.error = uno.pass_turn(state, me["id"])
        if not ss.error:
            uno.run_bots(state)
        push(state)
        st.rerun()
    if c.button("🔔 Call UNO", disabled=len(me["hand"]) != 1):
        uno.call_uno_late(state, me["id"])
        push(state)
        st.rerun()
    if d.button("🔄 Refresh"):
        st.rerun()

    auto_refresh(2, active=not my_turn)


# --------------------------------------------------------------------------- #
def auto_refresh(seconds: int, active: bool = True) -> None:
    on = st.sidebar.toggle("Auto-refresh", value=True, key="auto_rf",
                           help="Polls the server so you see other players' moves.")
    st.sidebar.caption("Turn this off if you want the screen to stay still.")
    if on and active:
        time.sleep(seconds)
        st.rerun()


def main() -> None:
    st.sidebar.markdown("### 🎴 UNO Online")
    if ss.room:
        st.sidebar.write(f"Room code: **{ss.room}**")
    st.sidebar.caption("Share the browser URL with friends — it carries the room code.")

    if not ss.room or not ss.pid:
        home()
        return
    state = reload_state()
    if not state:
        st.error("That room no longer exists.")
        if st.button("Back to home"):
            leave()
        return
    if state["started"]:
        table(state)
    else:
        lobby(state)


main()
