"""Local Tetris AI engine — Pierre Dellacherie placement evaluation.

This module is the ``make_move`` tool: given the current game state it
evaluates every (rotation x column) placement, simulates the hard-drop,
scores the resulting board, and returns the optimal action sequence or
a single steering action.

The algorithm mirrors the TypeScript agent.ts logic.
"""

from __future__ import annotations

from typing import Any

# ── Game constants (must match tetris.py) ─────────────────────────────
COLS = 10
ROWS = 20

# ── Evaluation weights (tuned for clean play) ────────────────────────
W_LINES = 500       # lines cleared  (positive — we WANT this)
W_HOLES = -400      # empty cells with filled above (very bad)
W_HEIGHT = -30      # aggregate column height (lower is better)
W_BUMPINESS = -50   # sum |h[i] - h[i-1]| (flatter is better)

# ── Piece shape definitions (must match tetris.py) ───────────────────
Cell = tuple[int, int]

SHAPES: dict[str, list[list[Cell]]] = {
    "I": [
        [(0, 0), (1, 0), (2, 0), (3, 0)],
        [(0, 0), (0, 1), (0, 2), (0, 3)],
    ],
    "O": [[(0, 0), (1, 0), (0, 1), (1, 1)]],
    "T": [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(0, 0), (0, 1), (1, 1), (0, 2)],
        [(0, 0), (1, 0), (2, 0), (1, 1)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "S": [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "Z": [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
    "J": [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(0, 0), (1, 0), (0, 1), (0, 2)],
        [(0, 0), (1, 0), (2, 0), (2, 1)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    "L": [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(0, 0), (0, 1), (0, 2), (1, 2)],
        [(0, 0), (1, 0), (2, 0), (0, 1)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}


# ── Piece helpers ─────────────────────────────────────────────────────

def _piece_cells(ptype: str, rot: int, px: int, py: int) -> list[Cell]:
    """Return the board cells occupied by a piece at (px, py) with rotation rot."""
    rots = SHAPES[ptype]
    r = rot % len(rots)
    return [(px + dx, py + dy) for dx, dy in rots[r]]


def _is_valid(cells: list[Cell], board: list[list[int]]) -> bool:
    """Check whether all cells are within bounds and unoccupied."""
    for cx, cy in cells:
        if cx < 0 or cx >= COLS or cy >= ROWS:
            return False
        if cy >= 0 and board[cy][cx] != 0:
            return False
    return True


def _drop_y(ptype: str, rot: int, px: int, start_y: int, board: list[list[int]]) -> int:
    """Drop piece straight down; return the final y position."""
    y = start_y
    while _is_valid(_piece_cells(ptype, rot, px, y + 1), board):
        y += 1
    return y


def _clone_board(board: list[list[int]]) -> list[list[int]]:
    return [row[:] for row in board]


def _lock_and_clear(ptype: str, rot: int, px: int, py: int,
                    board: list[list[int]]) -> int:
    """Lock piece onto board and clear full lines. Returns lines cleared."""
    for cx, cy in _piece_cells(ptype, rot, px, py):
        if 0 <= cy < ROWS:
            board[cy][cx] = 1
    cleared = 0
    r = ROWS - 1
    while r >= 0:
        if all(v != 0 for v in board[r]):
            board.pop(r)
            board.insert(0, [0] * COLS)
            cleared += 1
            # re-check same index
        else:
            r -= 1
    return cleared


# ── Board evaluation ──────────────────────────────────────────────────

def _col_heights(board: list[list[int]]) -> list[int]:
    """Height of the tallest occupied cell in each column."""
    heights = []
    for c in range(COLS):
        h = 0
        for r in range(ROWS):
            if board[r][c] != 0:
                h = ROWS - r
                break
        heights.append(h)
    return heights


def _aggregate_height(board: list[list[int]]) -> int:
    return sum(_col_heights(board))


def _count_holes(board: list[list[int]]) -> int:
    """Empty cells with at least one filled cell above in the same column."""
    holes = 0
    for c in range(COLS):
        filled = False
        for r in range(ROWS):
            if board[r][c] != 0:
                filled = True
            elif filled:
                holes += 1
    return holes


def _bumpiness(heights: list[int]) -> int:
    return sum(abs(heights[i] - heights[i + 1]) for i in range(len(heights) - 1))


def _eval_board(board: list[list[int]], lines_cleared: int) -> float:
    heights = _col_heights(board)
    return (
        W_LINES * lines_cleared
        + W_HOLES * _count_holes(board)
        + W_HEIGHT * _aggregate_height(board)
        + W_BUMPINESS * _bumpiness(heights)
    )


# ── Best placement finder ────────────────────────────────────────────

def _best_placement(ptype: str, num_rots: int,
                    board: list[list[int]]) -> tuple[int, int, float]:
    """Find the best (rot, x, score) placement for the given piece type."""
    best_rot = 0
    best_x = 0
    best_score = float("-inf")

    for rot in range(num_rots):
        # Find x range that keeps piece in bounds
        cells0 = _piece_cells(ptype, rot, 0, 0)
        min_dx = -min(dx for dx, _ in cells0)
        max_dx = COLS - 1 - max(dx for dx, _ in cells0)

        for x in range(min_dx, max_dx + 1):
            if not _is_valid(_piece_cells(ptype, rot, x, 0), board):
                continue
            final_y = _drop_y(ptype, rot, x, 0, board)
            sim = _clone_board(board)
            lines = _lock_and_clear(ptype, rot, x, final_y, sim)
            score = _eval_board(sim, lines)
            if score > best_score:
                best_rot = rot
                best_x = x
                best_score = score

    return best_rot, best_x, best_score


# ── Stateful agent ───────────────────────────────────────────────────

_last_piece_type: str = ""
_last_piece_rot: int = -1
_last_piece_x: int = -999
_stuck_frames: int = 0
_target_rot: int = 0
_target_x: int = 0


def decide_action(state: dict[str, Any]) -> str:
    """Decide the next action based on the current game state.

    Returns one of: ``'LEFT'``, ``'RIGHT'``, ``'ROTATE'``, ``'DROP'``.
    """
    global _last_piece_type, _last_piece_rot, _last_piece_x
    global _stuck_frames, _target_rot, _target_x

    piece = state["piece"]
    board = state["board"]
    ptype = piece["type"]
    num_rots = piece["num_rotations"]

    # Recompute target when a new piece spawns
    if ptype != _last_piece_type:
        rot, x, sc = _best_placement(ptype, num_rots, board)
        _target_rot = rot
        _target_x = x
        _last_piece_type = ptype
        _stuck_frames = 0
        print(f"  [AI] New piece={ptype}  best: rot={rot} x={x}  score={sc:.0f}")

    # Stuck detection
    if piece["rot"] == _last_piece_rot and piece["x"] == _last_piece_x:
        _stuck_frames += 1
        if _stuck_frames > 20:
            rot, x, sc = _best_placement(ptype, num_rots, board)
            _target_rot = rot
            _target_x = x
            _stuck_frames = 0
            print("  [AI] Recomputed target (stuck)")
    else:
        _stuck_frames = 0
        _last_piece_rot = piece["rot"]
        _last_piece_x = piece["x"]

    # Priority 1: Rotate until matching target
    if piece["rot"] != _target_rot % num_rots:
        return "ROTATE"

    # Priority 2: Translate left/right
    if piece["x"] < _target_x:
        return "RIGHT"
    if piece["x"] > _target_x:
        return "LEFT"

    # Priority 3: Aligned — hard drop
    _last_piece_type = ""  # reset for next piece
    return "DROP"


def get_macro_actions(state: dict[str, Any]) -> list[str]:
    """Compute the full action sequence to place the current piece optimally.

    Returns a list like ``['ROTATE', 'RIGHT', 'RIGHT', 'DROP']``.
    """
    global _last_piece_type

    piece = state["piece"]
    board = state["board"]
    ptype = piece["type"]
    num_rots = piece["num_rotations"]

    rot, x, sc = _best_placement(ptype, num_rots, board)
    print(f"  [AI] Macro: piece={ptype}  best: rot={rot} x={x}  score={sc:.0f}")

    actions: list[str] = []

    # Rotations needed
    current_rot = piece["rot"]
    while current_rot != rot % num_rots:
        actions.append("ROTATE")
        current_rot = (current_rot + 1) % num_rots

    # Horizontal movement
    current_x = piece["x"]
    while current_x < x:
        actions.append("RIGHT")
        current_x += 1
    while current_x > x:
        actions.append("LEFT")
        current_x -= 1

    actions.append("DROP")
    _last_piece_type = ""
    return actions


# ── State summary (for OmniLink memory) ─────────────────────────────

def state_summary(state: dict[str, Any]) -> str:
    """Build a concise text summary of the current game state."""
    score = state.get("score", 0)
    hiscore = state.get("hiscore", 0)
    level = state.get("level", 1)
    lines = state.get("lines", 0)
    lives = state.get("lives", 0)
    play_time = state.get("play_time", 0)
    game_state = state.get("game_state", "UNKNOWN")

    piece = state.get("piece", {})
    piece_type = piece.get("type", "?")
    next_piece = state.get("next_piece", "?")

    minutes = int(play_time) // 60
    seconds = int(play_time) % 60

    # Count filled cells on the board
    board = state.get("board", [])
    filled = sum(1 for row in board for cell in row if cell != 0)

    return (
        f"Game state: {game_state}\n"
        f"Score: {score} | Hi-score: {hiscore} | Level: {level}\n"
        f"Lines cleared: {lines} | Lives: {lives}\n"
        f"Play time: {minutes}m {seconds}s\n"
        f"Current piece: {piece_type} | Next piece: {next_piece}\n"
        f"Board fill: {filled} cells occupied"
    )
