# tetris.py ─ Full Pygame Tetris Clone
# Features: 7 tetrominoes, gravity, line-clearing, scoring, levels,
#           pause/resume, TITLE/PLAY/PAUSE/GAMEOVER states.
# AI_ENABLED = False — controlled entirely via server_wrapper.py (HTTP/MQTT agent).

import sys, math, random
import pygame

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
COLS, ROWS = 10, 20
CELL       = 30        # pixels per cell
FPS        = 60
AI_ENABLED = False     # never let a local AI run; server_wrapper overrides

# ─────────────────────────────────────────────────────────────────────────────
# Colors
# ─────────────────────────────────────────────────────────────────────────────
BLACK     = (8, 8, 20)
BG_LINE   = (12, 12, 28)
WHITE     = (240, 240, 240)
DARK_GREY = (40, 40, 40)
GREY      = (90, 90, 90)

PIECE_COLORS = {
    'I': (0,   240, 240),   # cyan
    'O': (240, 240,   0),   # yellow
    'T': (160,   0, 240),   # purple
    'S': (0,   240,   0),   # green
    'Z': (240,   0,   0),   # red
    'J': (0,     0, 240),   # blue
    'L': (240, 160,   0),   # orange
}
PIECE_TYPES = list(PIECE_COLORS)

# ─────────────────────────────────────────────────────────────────────────────
# Piece Shapes
# Each rotation = list of (col_offset, row_offset) from piece origin.
# ─────────────────────────────────────────────────────────────────────────────
SHAPES = {
    'I': [
        [(0,0),(1,0),(2,0),(3,0)],   # horizontal
        [(0,0),(0,1),(0,2),(0,3)],   # vertical
    ],
    'O': [
        [(0,0),(1,0),(0,1),(1,1)],
    ],
    'T': [
        [(1,0),(0,1),(1,1),(2,1)],   # T-up
        [(0,0),(0,1),(1,1),(0,2)],   # T-right
        [(0,0),(1,0),(2,0),(1,1)],   # T-down
        [(1,0),(0,1),(1,1),(1,2)],   # T-left
    ],
    'S': [
        [(1,0),(2,0),(0,1),(1,1)],
        [(0,0),(0,1),(1,1),(1,2)],
    ],
    'Z': [
        [(0,0),(1,0),(1,1),(2,1)],
        [(1,0),(0,1),(1,1),(0,2)],
    ],
    'J': [
        [(0,0),(0,1),(1,1),(2,1)],   # J-up
        [(0,0),(1,0),(0,1),(0,2)],   # J-right
        [(0,0),(1,0),(2,0),(2,1)],   # J-down
        [(1,0),(1,1),(0,2),(1,2)],   # J-left
    ],
    'L': [
        [(2,0),(0,1),(1,1),(2,1)],   # L-up
        [(0,0),(0,1),(0,2),(1,2)],   # L-right
        [(0,0),(1,0),(2,0),(0,1)],   # L-down
        [(0,0),(1,0),(1,1),(1,2)],   # L-left
    ],
}

def piece_cells(ptype, rot, px, py):
    """Return list of (board_col, board_row) for piece at position (px,py)."""
    return [(px + dx, py + dy) for dx, dy in SHAPES[ptype][rot % len(SHAPES[ptype])]]

# ─────────────────────────────────────────────────────────────────────────────
# High-score persistence
# ─────────────────────────────────────────────────────────────────────────────
HISCORE_FILE = ".tetris_hiscore"

def load_hiscore():
    try:
        with open(HISCORE_FILE) as f:
            return int(f.read().strip() or "0")
    except Exception:
        return 0

def save_hiscore(s):
    try:
        with open(HISCORE_FILE, "w") as f:
            f.write(str(s))
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Game class
# ─────────────────────────────────────────────────────────────────────────────
class Tetris:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Tetris — OmniLink Edition")

        board_w = COLS * CELL
        side_w  = 180
        hud_h   = 60
        self.base_w = board_w + side_w
        self.base_h = ROWS * CELL + hud_h

        self.screen       = pygame.display.set_mode((self.base_w, self.base_h), pygame.RESIZABLE)
        self.base_surface = pygame.Surface((self.base_w, self.base_h))
        self.clock        = pygame.time.Clock()
        self.font         = pygame.font.SysFont("consolas", 20)
        self.big          = pygame.font.SysFont("consolas", 36, bold=True)

        self.hiscore = load_hiscore()
        self.state   = "TITLE"   # TITLE | PLAY | PAUSE | GAMEOVER

        # Piece being controlled by the agent; set by server_wrapper
        self.pending_actions = []   # consumed in loop via update tick

        self._init_game()

    # ── Game state ─────────────────────────────────────────────────────────
    def _init_game(self):
        self.board  = [[0] * COLS for _ in range(ROWS)]   # 0=empty, 1-7=color index
        self.score  = 0
        self.level  = 1
        self.lines  = 0
        self.lives  = 15
        self.play_time = 0.0
        self.bag    = []          # 7-bag randomiser
        self.piece  = self._new_piece()
        self.next_t = self._next_from_bag()
        self.gravity_interval = self._gravity()
        self.gravity_accum    = 0.0
        self.lock_delay       = 0.0   # small delay before locking to floor
        self.ai_action_timer  = 0.0   # throttle for consuming pending_actions

    def _gravity(self):
        # Gradual exponential curve: starts at 1.0s/drop, hard floor at 0.05s
        # At t=60s: ~0.47s/drop, t=120s: ~0.22s/drop, t=300s: 0.05s floor
        return max(0.05, 1.0 * (0.92 ** (self.play_time / 15.0)))

    def _next_from_bag(self):
        if not self.bag:
            self.bag = PIECE_TYPES[:]
            random.shuffle(self.bag)
        return self.bag.pop()

    def _new_piece(self, ptype=None):
        t   = ptype or self._next_from_bag()
        rot = 0
        px  = COLS // 2 - 2   # spawn at horizontal centre
        py  = -2              # spawn slightly above the board
        return {'type': t, 'rot': rot, 'x': px, 'y': py}

    def _cells(self, piece=None, rot=None, px=None, py=None):
        p = piece or self.piece
        return piece_cells(
            p['type'],
            rot if rot is not None else p['rot'],
            px  if px  is not None else p['x'],
            py  if py  is not None else p['y'],
        )

    def _valid(self, cells):
        for cx, cy in cells:
            if cx < 0 or cx >= COLS or cy >= ROWS:
                return False
            if cy >= 0 and self.board[cy][cx]:
                return False
        return True

    # ── Piece actions ──────────────────────────────────────────────────────
    def _move(self, dx, dy):
        nc = self._cells(px=self.piece['x']+dx, py=self.piece['y']+dy)
        if self._valid(nc):
            self.piece['x'] += dx
            self.piece['y'] += dy
            if dx != 0:
                self.lock_delay = 0.0  # Modern Tetris move-reset lock delay
            return True
        return False

    def _rotate(self):
        new_rot = (self.piece['rot'] + 1) % len(SHAPES[self.piece['type']])
        nc = self._cells(rot=new_rot)
        # Simple wall-kick: try center, then ±1, ±2
        for kick in [0, -1, 1, -2, 2]:
            kc = piece_cells(self.piece['type'], new_rot,
                             self.piece['x'] + kick, self.piece['y'])
            if self._valid(kc):
                self.piece['rot'] = new_rot
                self.piece['x'] += kick
                self.lock_delay = 0.0  # reset on rotate
                return

    def _hard_drop(self):
        cells = 0
        while self._move(0, 1):
            cells += 1
        self.score += cells * 2
        self._lock()

    def _lock(self):
        game_over = False
        for cx, cy in self._cells():
            if cy >= 0:
                self.board[cy][cx] = PIECE_TYPES.index(self.piece['type']) + 1
            else:
                game_over = True
        self._clear_lines()

        if game_over:
            self._handle_game_over()
            return

        self.piece = self._new_piece(self.next_t)
        self.next_t = self._next_from_bag()
        self.gravity_accum = 0.0
        self.lock_delay = 0.0
        # Game over if new piece immediately overlaps
        if not self._valid(self._cells()):
            self._handle_game_over()

    def _handle_game_over(self):
        self.lives -= 1
        if self.lives > 0:
            # Wipe the board, keep score/time, and spawn a new piece
            for r in range(ROWS):
                for c in range(COLS):
                    self.board[r][c] = 0
            self.piece = self._new_piece()
            self.next_t = self._next_from_bag()
            self.gravity_accum = 0.0
            self.lock_delay = 0.0
        else:
            self.state = "GAMEOVER"
            if self.score > self.hiscore:
                self.hiscore = self.score
                save_hiscore(self.hiscore)

    def _clear_lines(self):
        full = [r for r in range(ROWS) if all(self.board[r])]
        for r in full:
            del self.board[r]
            self.board.insert(0, [0] * COLS)
        pts = [0, 100, 300, 500, 800][min(len(full), 4)] * self.level
        self.score += pts
        self.lines  += len(full)
        self.level   = 1 + self.lines // 10
        self.gravity_interval = self._gravity()
        if self.score > self.hiscore:
            self.hiscore = self.score
            save_hiscore(self.hiscore)

    # ── Update ─────────────────────────────────────────────────────────────
    def toggle_pause(self):
        if   self.state == "PLAY":  self.state = "PAUSE"
        elif self.state == "PAUSE": self.state = "PLAY"

    def start_game(self):
        self._init_game()
        self.state = "PLAY"

    def update(self, dt):
        if self.state != "PLAY":
            return

        self.play_time += dt
        self.gravity_interval = self._gravity()

        self.ai_action_timer += dt

        # Drain one queued action every 0.04s — fast enough for macro batches
        if self.pending_actions and self.ai_action_timer >= 0.04:
            self.ai_action_timer = 0.0
            action = self.pending_actions.pop(0)

            if action == "LEFT":      self._move(-1, 0)
            elif action == "RIGHT":   self._move(1,  0)
            elif action == "ROTATE":  self._rotate()
            elif action == "DOWN":
                if self._move(0,  1):
                    self.score += 1 # Soft drop score
            elif action == "DROP":    
                # Restored: This awards the drop score and instantly locks the piece
                self._hard_drop()

        # Standard Tetris Lock Delay Logic
        resting = not self._valid(self._cells(py=self.piece['y'] + 1))
        if resting:
            self.lock_delay += dt
            if self.lock_delay >= 0.5:
                self._lock()
                return
        else:
            self.lock_delay = 0.0

        # Gravity
        self.gravity_accum += dt
        if self.gravity_accum >= self.gravity_interval:
            steps = int(self.gravity_accum / self.gravity_interval)
            self.gravity_accum -= steps * self.gravity_interval
            for _ in range(steps):
                if not self._move(0, 1):
                    break

    # ── Rendering ──────────────────────────────────────────────────────────
    def _draw_cell(self, surf, cx, cy, color, ox=0, oy=0, size=CELL):
        rect = (ox + cx * size, oy + cy * size, size - 1, size - 1)
        pygame.draw.rect(surf, color, rect, border_radius=3)
        # Highlight
        hi = tuple(min(255, c + 60) for c in color)
        pygame.draw.rect(surf, hi, (rect[0], rect[1], rect[2], 3))
        pygame.draw.rect(surf, hi, (rect[0], rect[1], 3, rect[3]))

    def render(self):
        s = self.base_surface
        s.fill(BLACK)

        # Subtle scan lines on board
        for y in range(0, ROWS * CELL, 4):
            pygame.draw.line(s, BG_LINE, (0, y), (COLS * CELL, y))

        # Board background grid
        for r in range(ROWS):
            for c in range(COLS):
                rect = (c * CELL + 1, r * CELL + 1, CELL - 2, CELL - 2)
                pygame.draw.rect(s, DARK_GREY, rect, border_radius=2)
                # Subtle inner highlight
                pygame.draw.rect(s, (45, 45, 45), (rect[0], rect[1], rect[2], 1))

        # Locked pieces on board
        for r in range(ROWS):
            for c in range(COLS):
                idx = self.board[r][c]
                if idx:
                    self._draw_cell(s, c, r, PIECE_COLORS[PIECE_TYPES[idx - 1]])

        # Current piece + ghost
        if self.state == "PLAY":
            # Ghost
            gy = self.piece['y']
            while self._valid(self._cells(py=gy + 1)):
                gy += 1
            for cx, cy in self._cells(py=gy):
                if cy >= 0:
                    ghost_surf = pygame.Surface((CELL - 2, CELL - 2), pygame.SRCALPHA)
                    color = PIECE_COLORS[self.piece['type']]
                    pygame.draw.rect(ghost_surf, (*color, 40), (0, 0, CELL - 2, CELL - 2), border_radius=2)
                    pygame.draw.rect(ghost_surf, (*color, 80), (0, 0, CELL - 2, CELL - 2), 2, border_radius=2)
                    s.blit(ghost_surf, (cx * CELL + 1, cy * CELL + 1))
            # Actual piece
            color = PIECE_COLORS[self.piece['type']]
            for cx, cy in self._cells():
                if cy >= 0:
                    self._draw_cell(s, cx, cy, color)

        # Sidebar
        sx = COLS * CELL + 10
        sidebar_x = COLS * CELL

        # Sidebar background
        pygame.draw.rect(s, (15, 15, 30), (sidebar_x, 0, 180, self.base_h))
        pygame.draw.line(s, (40, 40, 60), (sidebar_x, 0), (sidebar_x, self.base_h), 1)

        def txt(text, y, color=WHITE):
            t = self.font.render(text, True, color)
            s.blit(t, (sx, y))

        def separator(y):
            pygame.draw.line(s, (40, 40, 60), (sx, y), (sx + 160, y), 1)

        txt("SCORE", 10, (100, 100, 140))
        txt(str(self.score), 32)
        separator(58)
        txt("BEST", 65, (100, 100, 140))
        txt(str(self.hiscore), 87)
        separator(113)
        txt("TIME", 120, (100, 100, 140))
        txt(f"{int(self.play_time)}s", 142)
        separator(168)
        txt("LIVES", 175, (100, 100, 140))
        txt(str(self.lives), 197)
        separator(223)
        txt("NEXT", 235, (100, 100, 140))

        # Next piece preview
        if self.state in ("PLAY", "PAUSE"):
            nc = PIECE_COLORS[self.next_t]
            cells = piece_cells(self.next_t, 0, 0, 0)
            for dx, dy in cells:
                self._draw_cell(s, dx, dy, nc, ox=sx, oy=265, size=22)

        # Overlay
        if self.state == "TITLE":
            self._overlay("TETRIS", "Press Enter / Space to start")
        elif self.state == "PAUSE":
            self._overlay("PAUSED", "Press P to resume")
        elif self.state == "GAMEOVER":
            self._overlay("GAME OVER", f"Score: {self.score}   Press Enter")

        # Scale to window
        ww, wh = self.screen.get_size()
        scale = min(ww / self.base_w, wh / self.base_h)
        sw, sh = int(self.base_w * scale), int(self.base_h * scale)
        scaled = pygame.transform.smoothscale(s, (sw, sh))
        self.screen.fill(BLACK)
        self.screen.blit(scaled, ((ww - sw) // 2, (wh - sh) // 2))
        pygame.display.flip()

    def _overlay(self, title, sub=None):
        ov = pygame.Surface((self.base_w, self.base_h), pygame.SRCALPHA)
        ov.fill((0, 0, 20, 190))
        self.base_surface.blit(ov, (0, 0))
        t = self.big.render(title, True, WHITE)
        cx = (self.base_w - t.get_width()) // 2
        self.base_surface.blit(t, (cx, self.base_h // 2 - 60))
        if sub:
            st = self.font.render(sub, True, (160, 160, 180))
            self.base_surface.blit(st, ((self.base_w - st.get_width()) // 2, self.base_h // 2))

    # ── Event handling ─────────────────────────────────────────────────────
    def handle_input(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                raise SystemExit
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    raise SystemExit
                if self.state in ("TITLE", "GAMEOVER") and ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.start_game()
                if self.state in ("PLAY", "PAUSE") and ev.key == pygame.K_p:
                    self.toggle_pause()
                # Manual keyboard override (for testing without the agent)
                if self.state == "PLAY" and AI_ENABLED:
                    if   ev.key == pygame.K_LEFT:  self._move(-1, 0)
                    elif ev.key == pygame.K_RIGHT: self._move(1,  0)
                    elif ev.key == pygame.K_UP:    self._rotate()
                    elif ev.key == pygame.K_DOWN:  self._move(0,  1)
                    elif ev.key == pygame.K_SPACE: self._hard_drop()

    # ── Main loop ──────────────────────────────────────────────────────────
    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            self.handle_input()
            self.update(dt)
            self.render()


if __name__ == "__main__":
    Tetris().run()
