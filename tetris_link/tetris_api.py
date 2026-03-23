"""HTTP client for the Tetris game server."""

from __future__ import annotations

import json
from typing import Any

import requests

SERVER_URL = "http://127.0.0.1:5001"

# Reuse a persistent session for connection pooling.
_session = requests.Session()


def get_state() -> dict[str, Any]:
    """Fetch the current game state from the server.

    Returns the parsed game state dict with keys: board, piece, next_piece,
    score, hiscore, level, lines, lives, play_time, game_state, cols, rows.
    """
    r = _session.get(f"{SERVER_URL}/data", timeout=2)
    data = r.json()
    payload = data.get("payload", "{}")
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def send_action(action: str) -> None:
    """Send a single action (LEFT, RIGHT, ROTATE, DOWN, DROP) to the game."""
    _session.post(
        f"{SERVER_URL}/callback",
        json={"action": action},
        timeout=2,
    )


def send_actions(actions: list[str]) -> None:
    """Send a batch of actions to the game."""
    _session.post(
        f"{SERVER_URL}/callback",
        json={"actions": actions},
        timeout=2,
    )


def start_game() -> None:
    """Send the /start command to begin the game."""
    _session.post(f"{SERVER_URL}/start", timeout=2)
