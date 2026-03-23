"""Play Tetris using OmniLink tool calling.

The AI agent calls the ``make_move`` tool, which acts as a local
Tetris AI controller.  The model never sees the game — it simply
triggers the tool.  The tool reads the game state, evaluates all
possible placements, and sends the optimal action accordingly.

This keeps API credit usage to a minimum (one call to kick off).

Usage
-----
    python -u play_tetris.py
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

# ── Path setup ─────────────────────────────────────────────────────────
_HERE = str(pathlib.Path(__file__).resolve().parent)
LIB_PATH = str(pathlib.Path(__file__).resolve().parents[3] / "omnilink-lib" / "src")
if _HERE in sys.path:
    sys.path.remove(_HERE)
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from omnilink.tool_runner import ToolRunner

if _HERE not in sys.path:
    sys.path.append(_HERE)

from tetris_api import get_state, send_action, send_actions, start_game
from tetris_engine import decide_action, get_macro_actions, state_summary

USE_MACRO = True


class TetrisRunner(ToolRunner):
    agent_name = "tetris-agent"
    display_name = "Tetris"
    tool_description = "Place current piece optimally."

    def __init__(self) -> None:
        self._last_score = 0
        self._last_lives = -1
        self._last_level = -1
        self._last_lines = 0
        self._last_piece_type = ""

    def get_state(self) -> dict[str, Any]:
        return get_state()

    def execute_action(self, state: dict[str, Any]) -> None:
        if state.get("game_state") != "PLAY":
            return

        piece_type = state.get("piece", {}).get("type", "")

        if USE_MACRO and piece_type != self._last_piece_type and piece_type:
            actions = get_macro_actions(state)
            try:
                send_actions(actions)
            except Exception:
                pass
            self._last_piece_type = piece_type
        elif not USE_MACRO:
            action = decide_action(state)
            try:
                send_action(action)
            except Exception:
                pass

    def state_summary(self, state: dict[str, Any]) -> str:
        return state_summary(state)

    def is_game_over(self, state: dict[str, Any]) -> bool:
        return state.get("game_state") == "GAMEOVER"

    def game_over_message(self, state: dict[str, Any]) -> str:
        return (
            f"GAME OVER — Final score: {state.get('score', 0)}, "
            f"Level: {state.get('level', 1)}, Lines: {state.get('lines', 0)}"
        )

    def on_start(self) -> None:
        try:
            start_game()
            print("  Game started.")
        except Exception:
            pass

    def log_events(self, state: dict[str, Any]) -> None:
        score = state.get("score", 0)
        lives = state.get("lives", 0)
        level = state.get("level", 1)
        lines = state.get("lines", 0)
        piece_type = state.get("piece", {}).get("type", "")

        if score != self._last_score:
            print(f"  Score: {score}  (+{score - self._last_score})")
            self._last_score = score
        if lives != self._last_lives:
            if self._last_lives > 0 and lives < self._last_lives:
                print(f"  ** Life lost! Lives: {lives}")
            self._last_lives = lives
        if level != self._last_level:
            print(f"  Level: {level}")
            self._last_level = level
        if lines != self._last_lines:
            print(f"  Lines cleared: {lines} total")
            self._last_lines = lines


if __name__ == "__main__":
    TetrisRunner().run()
