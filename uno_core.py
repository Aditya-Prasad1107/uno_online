"""UNO rules engine.

Pure functions over a JSON-serialisable game-state dict, so the whole game can
be persisted in SQLite and shared between browsers.

Card format: {"c": <colour>, "v": <value>}
  colour: "R" | "G" | "B" | "Y" | "W"   (W = wild, colour chosen on play)
  value : "0".."9" | "skip" | "rev" | "+2" | "wild" | "+4"
"""

from __future__ import annotations

import random
import uuid
from typing import Any, Dict, List, Optional

COLORS = ["R", "G", "B", "Y"]
COLOR_NAMES = {"R": "Red", "G": "Green", "B": "Blue", "Y": "Yellow", "W": "Wild"}
COLOR_HEX = {"R": "#e4342a", "G": "#3aa63a", "B": "#1f7ae0", "Y": "#e8b21a", "W": "#2b2b2b"}
ACTION_LABEL = {"skip": "Skip", "rev": "Reverse", "+2": "+2", "wild": "Wild", "+4": "Wild +4"}

MAX_PLAYERS = 8
MIN_PLAYERS = 2


# --------------------------------------------------------------------------- #
# Deck
# --------------------------------------------------------------------------- #
def build_deck() -> List[Dict[str, str]]:
    """Standard 108-card UNO deck."""
    deck: List[Dict[str, str]] = []
    for c in COLORS:
        deck.append({"c": c, "v": "0"})
        for n in range(1, 10):
            deck += [{"c": c, "v": str(n)}] * 2
        for a in ("skip", "rev", "+2"):
            deck += [{"c": c, "v": a}] * 2
    deck += [{"c": "W", "v": "wild"}] * 4
    deck += [{"c": "W", "v": "+4"}] * 4
    return deck


def card_label(card: Dict[str, str]) -> str:
    v = card["v"]
    return ACTION_LABEL.get(v, v)


def card_text(card: Dict[str, str]) -> str:
    """Human readable, e.g. 'Red 7' or 'Wild +4'."""
    if card["c"] == "W":
        return ACTION_LABEL[card["v"]]
    return f"{COLOR_NAMES[card['c']]} {card_label(card)}"


# --------------------------------------------------------------------------- #
# Game creation / lobby
# --------------------------------------------------------------------------- #
def new_game(room: str, num_players: int, host_name: str, rules: Optional[dict] = None) -> Dict[str, Any]:
    num_players = max(MIN_PLAYERS, min(MAX_PLAYERS, int(num_players)))
    rules = rules or {}
    state: Dict[str, Any] = {
        "room": room.upper(),
        "num_players": num_players,
        "rules": {
            "stacking": bool(rules.get("stacking", True)),        # stack +2 on +2, +4 on +4
            "draw_to_match": bool(rules.get("draw_to_match", False)),  # keep drawing until playable
            "uno_penalty": bool(rules.get("uno_penalty", True)),  # +2 if caught not calling UNO
            "hand_size": int(rules.get("hand_size", 7)),
        },
        "players": [],
        "started": False,
        "finished": False,
        "winner": None,
        "draw": [],
        "discard": [],
        "current": 0,
        "direction": 1,
        "pending_draw": 0,
        "pending_kind": None,      # "+2" or "+4"
        "active_color": None,
        "turn_no": 0,
        "must_choose_color": False,
        "idle_turns": 0,
        "log": [],
        "version": 0,
    }
    add_player(state, host_name, is_bot=False)
    return state


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def add_player(state: dict, name: str, is_bot: bool = False) -> Optional[str]:
    if state["started"] or len(state["players"]) >= state["num_players"]:
        return None
    name = (name or "Player").strip()[:18] or "Player"
    existing = {p["name"] for p in state["players"]}
    base, i = name, 2
    while name in existing:
        name = f"{base} {i}"
        i += 1
    pid = _uid()
    state["players"].append({
        "id": pid, "name": name, "is_bot": is_bot,
        "hand": [], "said_uno": False, "caught": False,
    })
    log(state, f"**{name}** joined{' (bot)' if is_bot else ''}.")
    return pid


def remove_player(state: dict, pid: str) -> None:
    if state["started"]:
        return
    state["players"] = [p for p in state["players"] if p["id"] != pid]


def fill_with_bots(state: dict) -> None:
    n = 1
    while len(state["players"]) < state["num_players"]:
        add_player(state, f"Bot {n}", is_bot=True)
        n += 1


def log(state: dict, msg: str) -> None:
    state["log"].insert(0, msg)
    del state["log"][40:]


# --------------------------------------------------------------------------- #
# Start / deal
# --------------------------------------------------------------------------- #
def start_game(state: dict) -> None:
    if state["started"] or len(state["players"]) < MIN_PLAYERS:
        return
    deck = build_deck()
    random.shuffle(deck)
    hs = state["rules"]["hand_size"]
    for p in state["players"]:
        p["hand"] = [deck.pop() for _ in range(hs)]
        p["said_uno"] = False
        p["caught"] = False

    # First discard must be a number card (simplest fair start).
    idx = next(i for i, c in enumerate(deck) if c["v"].isdigit())
    first = deck.pop(idx)
    state["discard"] = [first]
    state["draw"] = deck
    state["active_color"] = first["c"]
    state["current"] = random.randrange(len(state["players"]))
    state["direction"] = 1
    state["pending_draw"] = 0
    state["pending_kind"] = None
    state["started"] = True
    state["finished"] = False
    state["winner"] = None
    state["turn_no"] = 1
    state["idle_turns"] = 0
    log(state, f"Game started. Top card: **{card_text(first)}**. "
               f"**{state['players'][state['current']]['name']}** goes first.")


def restart_game(state: dict) -> None:
    state["started"] = False
    state["finished"] = False
    state["winner"] = None
    state["log"] = []
    for p in state["players"]:
        p["hand"] = []
    start_game(state)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def top_card(state: dict) -> Dict[str, str]:
    return state["discard"][-1]


def current_player(state: dict) -> dict:
    return state["players"][state["current"]]


def player_by_id(state: dict, pid: str) -> Optional[dict]:
    return next((p for p in state["players"] if p["id"] == pid), None)


def seat_of(state: dict, pid: str) -> int:
    return next((i for i, p in enumerate(state["players"]) if p["id"] == pid), -1)


def _reshuffle_if_needed(state: dict) -> None:
    if state["draw"]:
        return
    keep = state["discard"][-1:]
    pool = state["discard"][:-1]
    if not pool:
        return
    for c in pool:                      # wilds lose their chosen colour
        if c["v"] in ("wild", "+4"):
            c["c"] = "W"
    random.shuffle(pool)
    state["draw"] = pool
    state["discard"] = keep
    log(state, "Draw pile reshuffled from the discard pile.")


def _draw_cards(state: dict, player: dict, n: int) -> List[dict]:
    got = []
    for _ in range(n):
        _reshuffle_if_needed(state)
        if not state["draw"]:
            break
        got.append(state["draw"].pop())
    player["hand"] += got
    if len(player["hand"]) > 1:
        player["said_uno"] = False
    return got


def is_playable(state: dict, card: dict) -> bool:
    """Can this card legally be played right now?"""
    top = top_card(state)
    # A pending draw stack must be answered with a matching stack card (or taken).
    if state["pending_draw"] > 0:
        if not state["rules"]["stacking"]:
            return False
        return card["v"] == state["pending_kind"]
    if card["c"] == "W":
        return True
    return card["c"] == state["active_color"] or card["v"] == top["v"]


def playable_indices(state: dict, player: dict) -> List[int]:
    return [i for i, c in enumerate(player["hand"]) if is_playable(state, c)]


def _advance(state: dict, steps: int = 1) -> None:
    n = len(state["players"])
    state["current"] = (state["current"] + state["direction"] * steps) % n
    state["turn_no"] += 1


# --------------------------------------------------------------------------- #
# Moves
# --------------------------------------------------------------------------- #
def play_card(state: dict, pid: str, hand_index: int, chosen_color: Optional[str] = None,
              call_uno: bool = False) -> str:
    """Play a card. Returns '' on success or an error message."""
    if not state["started"] or state["finished"]:
        return "Game is not running."
    p = current_player(state)
    if p["id"] != pid:
        return "It is not your turn."
    if not (0 <= hand_index < len(p["hand"])):
        return "That card is gone."
    card = p["hand"][hand_index]
    if not is_playable(state, card):
        return f"{card_text(card)} can't be played on {card_text(top_card(state))}."
    if card["c"] == "W" and chosen_color not in COLORS:
        return "Pick a colour for your wild card."

    p["hand"].pop(hand_index)
    played = dict(card)
    if played["c"] == "W":
        played["chosen"] = chosen_color
    state["discard"].append(played)
    state["active_color"] = chosen_color if card["c"] == "W" else card["c"]

    state["idle_turns"] = 0
    p["said_uno"] = bool(call_uno) and len(p["hand"]) == 1
    p["caught"] = False
    suffix = f" → **{COLOR_NAMES[state['active_color']]}**" if card["c"] == "W" else ""
    log(state, f"**{p['name']}** played {card_text(card)}{suffix}.")

    # Win check
    if not p["hand"]:
        state["finished"] = True
        state["winner"] = p["name"]
        log(state, f"🏆 **{p['name']}** wins the round!")
        return ""

    if len(p["hand"]) == 1 and p["said_uno"]:
        log(state, f"**{p['name']}** calls UNO!")

    v = card["v"]
    if v == "rev":
        if len(state["players"]) == 2:
            _advance(state, 2)          # acts as a skip in a 2-player game
        else:
            state["direction"] *= -1
            log(state, "Direction reversed.")
            _advance(state, 1)
    elif v == "skip":
        nxt = state["players"][(state["current"] + state["direction"]) % len(state["players"])]
        log(state, f"**{nxt['name']}** is skipped.")
        _advance(state, 2)
    elif v in ("+2", "+4"):
        state["pending_draw"] += 2 if v == "+2" else 4
        state["pending_kind"] = v
        _advance(state, 1)
    else:
        _advance(state, 1)
    return ""


def draw_or_take(state: dict, pid: str) -> str:
    """Draw a card, or absorb a pending +2/+4 stack."""
    if not state["started"] or state["finished"]:
        return "Game is not running."
    p = current_player(state)
    if p["id"] != pid:
        return "It is not your turn."

    if state["pending_draw"] > 0:
        n = state["pending_draw"]
        _draw_cards(state, p, n)
        log(state, f"**{p['name']}** takes {n} cards.")
        state["pending_draw"] = 0
        state["pending_kind"] = None
        _advance(state, 1)
        return ""

    if state["rules"]["draw_to_match"]:
        drawn = 0
        while drawn <= 40:
            got = _draw_cards(state, p, 1)
            if not got:
                break
            drawn += 1
            if is_playable(state, got[0]):
                break
        if drawn:
            state["idle_turns"] = 0
            log(state, f"**{p['name']}** drew {drawn} card{'s' if drawn > 1 else ''}.")
            if playable_indices(state, p):
                return ""                # keep the turn: they may play now
        else:
            _note_idle(state)
        _advance(state, 1)
        return ""

    got = _draw_cards(state, p, 1)
    if got:
        state["idle_turns"] = 0
        log(state, f"**{p['name']}** drew a card.")
        if is_playable(state, got[0]):
            return ""                    # keep the turn: they may play it or pass
    else:
        _note_idle(state)
    _advance(state, 1)
    return ""


def _note_idle(state: dict) -> None:
    """Nothing could be drawn or played — detect a fully stalled round."""
    state["idle_turns"] = int(state.get("idle_turns", 0)) + 1
    if state["idle_turns"] >= len(state["players"]):
        best = min(state["players"], key=lambda q: len(q["hand"]))
        state["finished"] = True
        state["winner"] = best["name"]
        log(state, f"Deck exhausted and nobody can move — "
                   f"**{best['name']}** wins on fewest cards.")


def pass_turn(state: dict, pid: str) -> str:
    p = current_player(state)
    if p["id"] != pid:
        return "It is not your turn."
    log(state, f"**{p['name']}** passed.")
    if not playable_indices(state, p) and not state["draw"]:
        _note_idle(state)
    _advance(state, 1)
    return ""


def call_uno_late(state: dict, pid: str) -> str:
    p = player_by_id(state, pid)
    if p and len(p["hand"]) == 1:
        p["said_uno"] = True
        log(state, f"**{p['name']}** calls UNO!")
    return ""


def catch_player(state: dict, accuser_id: str, target_id: str) -> str:
    """Catch someone on one card who never called UNO → they draw 2."""
    if not state["rules"]["uno_penalty"]:
        return "UNO penalties are off in this room."
    a = player_by_id(state, accuser_id)
    t = player_by_id(state, target_id)
    if not t or not a or t["id"] == a["id"]:
        return "Invalid catch."
    if len(t["hand"]) == 1 and not t["said_uno"] and not t["caught"]:
        t["caught"] = True
        _draw_cards(state, t, 2)
        log(state, f"**{a['name']}** caught **{t['name']}** not saying UNO — +2 cards!")
        return ""
    return "Nothing to catch there."


# --------------------------------------------------------------------------- #
# Bot
# --------------------------------------------------------------------------- #
def _best_color(hand: List[dict]) -> str:
    counts = {c: 0 for c in COLORS}
    for card in hand:
        if card["c"] in counts:
            counts[card["c"]] += 1
    return max(counts, key=counts.get)


def bot_move(state: dict) -> None:
    """Play one move for the current (bot) player."""
    p = current_player(state)
    if not p["is_bot"] or state["finished"]:
        return
    opts = playable_indices(state, p)
    if not opts:
        draw_or_take(state, p["id"])
        # If drawing kept the turn, try once more to play.
        if state["started"] and not state["finished"] and current_player(state)["id"] == p["id"]:
            opts = playable_indices(state, p)
            if opts:
                _bot_play(state, p, opts)
            else:
                pass_turn(state, p["id"])
        return
    _bot_play(state, p, opts)


def _bot_play(state: dict, p: dict, opts: List[int]) -> None:
    # Hold wilds back as escape cards; lead with colour-pressure cards.
    priority = {"+2": 5, "skip": 4, "rev": 4, "+4": 1, "wild": 1}

    def score(i: int) -> int:
        card = p["hand"][i]
        s = priority.get(card["v"], 2)
        if card["c"] == state["active_color"]:
            s += 1
        return s

    idx = max(opts, key=score)
    color = _best_color([c for j, c in enumerate(p["hand"]) if j != idx]) \
        if p["hand"][idx]["c"] == "W" else None
    play_card(state, p["id"], idx, color, call_uno=len(p["hand"]) == 2)


def run_bots(state: dict, limit: int = 12) -> bool:
    """Let consecutive bots take their turns. True if anything happened."""
    moved = False
    for _ in range(limit):
        if not state["started"] or state["finished"]:
            break
        if not current_player(state)["is_bot"]:
            break
        bot_move(state)
        moved = True
    return moved
