/**
 * OmniLink Tetris Agent
 * ─────────────────────────────────────────────────────────────
 * Target : Browser / OmniLink Tool environment (ESM / isolated Worker)
 *
 * Architecture:
 *   GET  http://localhost:5001/data      ← board + current piece + next piece
 *   POST http://localhost:5001/callback  → action: LEFT|RIGHT|ROTATE|DOWN|DROP
 *   MQTT ws://localhost:9001  olink/commands  ← pause/resume
 *
 * AI Strategy (Pierre Dellacherie evaluation):
 *   For every (rotation × column) placement of the current piece:
 *     1. Simulate hard-drop on a copy of the board.
 *     2. Score the result: lines cleared, holes, aggregate height, bumpiness.
 *     3. Pick the best placement.
 *   Then each poll sends ONE command to steer the piece toward target:
 *     ROTATE → … → ROTATE (until rotation matches)
 *     LEFT / RIGHT (until x matches)
 *     DROP  (when aligned)
 */

// ── Logging flags ─────────────────────────────────────────────────────────────
const LOG_DECISION = true;   // log best placement each decision
const LOG_ACTION = true;   // log each action sent
const LOG_EVENTS = true;   // score / level changes
const LOG_IDLE = false;
const LOG_MQTT = true;
const LOG_ERRORS = true;

// ── Config ────────────────────────────────────────────────────────────────────
const API_URL = "http://localhost:5001";
const POLL_DELAY_MS = 60;
const MQTT_WS_URL = "ws://localhost:9001";
const CMD_TOPIC = "olink/commands";

const COLS = 10;
const ROWS = 20;

// ── Evaluation weights (tuned for clean play) ─────────────────────────────────
const W_LINES = 500;   // lines cleared  (positive – we WANT this)
const W_HOLES = -400;   // empty cells with filled above (very bad)
const W_HEIGHT = -30;   // aggregate column height (lower is better)
const W_BUMPINESS = -50;   // sum |h[i] - h[i-1]| (flatter is better)

// ── Interfaces ────────────────────────────────────────────────────────────────
interface PyState {
    command: "IDLE" | "ACTIVATE";
    payload: string;
    version: number;
}

interface PieceInfo {
    type: string;
    rot: number;
    x: number;
    y: number;
    num_rotations: number;
}

interface GameState {
    type: "state";
    board: number[][];   // ROWS×COLS, 0=empty
    piece: PieceInfo;
    next_piece: string;
    score: number;
    hiscore: number;
    level: number;
    lines: number;
    game_state: string;
    cols: number;
    rows: number;
}

interface AgentAction {
    action: "LEFT" | "RIGHT" | "ROTATE" | "DOWN" | "DROP" | "STOP";
    version: number;
    timestamp: string;
}

// ── Piece shape definitions (must match tetris.py) ────────────────────────────
type Cell = [number, number];

const SHAPES: Record<string, Cell[][]> = {
    I: [
        [[0, 0], [1, 0], [2, 0], [3, 0]],
        [[0, 0], [0, 1], [0, 2], [0, 3]],
    ],
    O: [[[0, 0], [1, 0], [0, 1], [1, 1]]],
    T: [
        [[1, 0], [0, 1], [1, 1], [2, 1]],
        [[0, 0], [0, 1], [1, 1], [0, 2]],
        [[0, 0], [1, 0], [2, 0], [1, 1]],
        [[1, 0], [0, 1], [1, 1], [1, 2]],
    ],
    S: [
        [[1, 0], [2, 0], [0, 1], [1, 1]],
        [[0, 0], [0, 1], [1, 1], [1, 2]],
    ],
    Z: [
        [[0, 0], [1, 0], [1, 1], [2, 1]],
        [[1, 0], [0, 1], [1, 1], [0, 2]],
    ],
    J: [
        [[0, 0], [0, 1], [1, 1], [2, 1]],
        [[0, 0], [1, 0], [0, 1], [0, 2]],
        [[0, 0], [1, 0], [2, 0], [2, 1]],
        [[1, 0], [1, 1], [0, 2], [1, 2]],
    ],
    L: [
        [[2, 0], [0, 1], [1, 1], [2, 1]],
        [[0, 0], [0, 1], [0, 2], [1, 2]],
        [[0, 0], [1, 0], [2, 0], [0, 1]],
        [[0, 0], [1, 0], [1, 1], [1, 2]],
    ],
};

function pieceCells(ptype: string, rot: number, px: number, py: number): Cell[] {
    const rots = SHAPES[ptype];
    const r = ((rot % rots.length) + rots.length) % rots.length;
    return rots[r].map(([dx, dy]) => [px + dx, py + dy] as Cell);
}

// ── Board simulation helpers ───────────────────────────────────────────────────
function cloneBoard(board: number[][]): number[][] {
    return board.map(row => [...row]);
}

function isValid(cells: Cell[], board: number[][]): boolean {
    for (const [cx, cy] of cells) {
        if (cx < 0 || cx >= COLS || cy >= ROWS) return false;
        if (cy >= 0 && board[cy][cx] !== 0) return false;
    }
    return true;
}

/** Drop cells straight down until they rest, return final y offset from initial py. */
function dropY(ptype: string, rot: number, px: number, startY: number, board: number[][]): number {
    let y = startY;
    while (isValid(pieceCells(ptype, rot, px, y + 1), board)) y++;
    return y;
}

/** Lock piece onto board and clear full lines. Returns # lines cleared. */
function lockAndClear(ptype: string, rot: number, px: number, py: number, board: number[][]): number {
    for (const [cx, cy] of pieceCells(ptype, rot, px, py)) {
        if (cy >= 0) board[cy][cx] = 1;
    }
    let cleared = 0;
    for (let r = ROWS - 1; r >= 0; r--) {
        if (board[r].every(v => v !== 0)) {
            board.splice(r, 1);
            board.unshift(new Array(COLS).fill(0));
            cleared++;
            r++;  // re-check same index
        }
    }
    return cleared;
}

/** Aggregate height: sum of highest occupied row in each column. */
function aggregateHeight(board: number[][]): number {
    let total = 0;
    for (let c = 0; c < COLS; c++) {
        for (let r = 0; r < ROWS; r++) {
            if (board[r][c] !== 0) { total += ROWS - r; break; }
        }
    }
    return total;
}

/** Column heights (height of tallest piece in each column). */
function colHeights(board: number[][]): number[] {
    return Array.from({ length: COLS }, (_, c) => {
        for (let r = 0; r < ROWS; r++) {
            if (board[r][c] !== 0) return ROWS - r;
        }
        return 0;
    });
}

/** Holes: empty cells with at least one filled cell above in the same column. */
function countHoles(board: number[][]): number {
    let holes = 0;
    for (let c = 0; c < COLS; c++) {
        let filled = false;
        for (let r = 0; r < ROWS; r++) {
            if (board[r][c] !== 0) filled = true;
            else if (filled) holes++;
        }
    }
    return holes;
}

/** Bumpiness: sum of absolute height differences between adjacent columns. */
function bumpiness(heights: number[]): number {
    let b = 0;
    for (let i = 0; i < heights.length - 1; i++) {
        b += Math.abs(heights[i] - heights[i + 1]);
    }
    return b;
}

/** Score a board configuration after a simulated placement. */
function evalBoard(board: number[][], linesCleared: number): number {
    const heights = colHeights(board);
    return (
        W_LINES * linesCleared +
        W_HOLES * countHoles(board) +
        W_HEIGHT * aggregateHeight(board) +
        W_BUMPINESS * bumpiness(heights)
    );
}

// ── Best placement finder ──────────────────────────────────────────────────────
interface Placement {
    rot: number;
    x: number;
    score: number;
}

function bestPlacement(ptype: string, numRots: number, board: number[][]): Placement {
    let best: Placement = { rot: 0, x: 0, score: -Infinity };

    for (let rot = 0; rot < numRots; rot++) {
        // Find x range that keeps piece in bounds
        const cells0 = pieceCells(ptype, rot, 0, 0);
        const minDx = -Math.min(...cells0.map(([dx]) => dx));
        const maxDx = COLS - 1 - Math.max(...cells0.map(([dx]) => dx));

        for (let x = minDx; x <= maxDx; x++) {
            // Check piece can actually enter from the top without immediate collision
            if (!isValid(pieceCells(ptype, rot, x, 0), board)) continue;

            const finalY = dropY(ptype, rot, x, 0, board);
            const sim = cloneBoard(board);
            const lines = lockAndClear(ptype, rot, x, finalY, sim);
            const score = evalBoard(sim, lines);

            if (score > best.score) {
                best = { rot, x, score };
            }
        }
    }

    return best;
}

// ── Agent state ───────────────────────────────────────────────────────────────
let lastVersion = -1;
let lastScore = 0;
let lastLevel = 1;
let lastLines = 0;
let lastGameState = "";
let targetRot = 0;
let targetX = 0;
let targetDecided = false;   // has a target been chosen for the current piece?
let lastPieceType = "";
let lastPieceRot = -1;
let lastPieceX = -999;
let stuckFrames = 0;

// ── Action decision ───────────────────────────────────────────────────────────
function decideAction(state: GameState): AgentAction["action"] {
    const { piece, board } = state;

    // ── Recompute target whenever the piece type changes (new piece spawned) ──
    if (piece.type !== lastPieceType) {
        const p = bestPlacement(piece.type, piece.num_rotations, board);
        targetRot = p.rot;
        targetX = p.x;
        targetDecided = true;
        lastPieceType = piece.type;
        stuckFrames = 0;
        if (LOG_DECISION) {
            console.log(
                `[AI] New piece=${piece.type}  best: rot=${p.rot} x=${targetX}  score=${p.score.toFixed(0)}`
            );
        }
    }

    // ── Stuck detection: if piece hasn't moved for a while, recompute ─────────
    if (piece.rot === lastPieceRot && piece.x === lastPieceX) {
        stuckFrames++;
        if (stuckFrames > 20) {
            // Force recompute
            const p = bestPlacement(piece.type, piece.num_rotations, board);
            targetRot = p.rot;
            targetX = p.x;
            stuckFrames = 0;
            if (LOG_DECISION) console.log(`[AI] ♻️ Recomputed target (stuck)`);
        }
    } else {
        stuckFrames = 0;
        lastPieceRot = piece.rot;
        lastPieceX = piece.x;
    }

    // ── Priority 1: Rotate until we match target rotation ────────────────────
    const numRots = piece.num_rotations;
    if (piece.rot !== targetRot % numRots) {
        return "ROTATE";
    }

    // ── Priority 2: Translate left/right ─────────────────────────────────────
    if (piece.x < targetX) return "RIGHT";
    if (piece.x > targetX) return "LEFT";

    // ── Priority 3: Aligned – hard drop ──────────────────────────────────────
    if (LOG_ACTION) console.log(`[AI] 🔻 DROP  piece=${piece.type} rot=${piece.rot} x=${piece.x}`);
    // Reset for next piece
    lastPieceType = "";
    return "DROP";
}

// ── Main poll loop ────────────────────────────────────────────────────────────
async function agentLoop(): Promise<void> {
    try {
        const res = await fetch(`${API_URL}/data`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const wrapper: PyState = await res.json();

        if (wrapper.command === "ACTIVATE" && wrapper.version > lastVersion) {
            lastVersion = wrapper.version;
            const state: GameState = JSON.parse(wrapper.payload);

            // ── Event logging ──────────────────────────────────────────────
            if (state.score !== lastScore) {
                if (LOG_EVENTS) console.log(`[GAME] 🔶 Score ${lastScore} → ${state.score} (+${state.score - lastScore})`);
                lastScore = state.score;
            }
            if (state.level !== lastLevel) {
                if (LOG_EVENTS) console.log(`[GAME] 🎉 Level ${lastLevel} → ${state.level}`);
                lastLevel = state.level;
            }
            if (state.lines !== lastLines) {
                if (LOG_EVENTS) console.log(`[GAME] ✅ Lines cleared: ${state.lines} total`);
                lastLines = state.lines;
            }
            if (state.game_state !== lastGameState) {
                console.log(`[GAME] State → ${state.game_state}`);
                lastGameState = state.game_state;
                if (state.game_state !== "PLAY") {
                    lastPieceType = "";   // reset on death / game over
                }
            }

            const action = decideAction(state);
            if (LOG_ACTION && action !== "DROP")
                console.log(`[AI] → ${action}  piece=(${state.piece.type} rot=${state.piece.rot} x=${state.piece.x}) target=(rot=${targetRot} x=${targetX})`);

            const payload: AgentAction = {
                action,
                version: wrapper.version,
                timestamp: new Date().toISOString(),
            };

            await fetch(`${API_URL}/callback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

        } else if (wrapper.command === "IDLE") {
            if (LOG_IDLE) console.log(`[AGENT] IDLE v=${wrapper.version}`);
        }

    } catch (err: unknown) {
        if (LOG_ERRORS) {
            const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
            console.error(`[AGENT] Error: ${msg}`);
        }
    }
}

// ── MQTT pause/resume (globalThis-safe for Workers) ───────────────────────────
const _g = globalThis as Record<string, unknown>;

function sendMqttCmd(cmd: "pause" | "resume"): void {
    const client = _g["mqttClient"] as any;
    if (!client) { console.warn("[MQTT] Not connected."); return; }
    const payload = JSON.stringify({ command: cmd });
    client.publish(CMD_TOPIC, payload);
    if (LOG_MQTT) console.log(`[MQTT] → '${CMD_TOPIC}': ${payload}`);
}

_g["pauseGame"] = () => sendMqttCmd("pause");
_g["resumeGame"] = () => sendMqttCmd("resume");

async function initMqtt(): Promise<void> {
    try {
        const lib = _g["mqtt"] as any;
        if (!lib) {
            console.warn("[MQTT] No global mqtt lib – pause/resume unavailable.");
            return;
        }
        const client = lib.connect(MQTT_WS_URL, { clientId: `tetris-agent-${Date.now()}` });
        client.on("connect", () => {
            if (LOG_MQTT) console.log(`[MQTT] ✅ Connected to ${MQTT_WS_URL}`);
            _g["mqttClient"] = client;
        });
        client.on("error", (e: Error) => { if (LOG_ERRORS) console.error("[MQTT]", e.message); });
        client.on("close", () => { if (LOG_MQTT) console.log("[MQTT] Disconnected."); });
    } catch (err) {
        if (LOG_ERRORS) console.error("[MQTT] Init failed:", err);
    }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
console.log("╔══════════════════════════════════════════════╗");
console.log("║  🧱  OmniLink Tetris Agent  (BFS Placement)   ║");
console.log("╚══════════════════════════════════════════════╝");
console.log(`[CONFIG] API   : ${API_URL}  (poll every ${POLL_DELAY_MS}ms)`);
console.log(`[CONFIG] MQTT  : ${MQTT_WS_URL}  topic='${CMD_TOPIC}'`);
console.log(`[WEIGHTS] lines=${W_LINES} holes=${W_HOLES} height=${W_HEIGHT} bumpiness=${W_BUMPINESS}`);
console.log("[INFO]   globalThis.pauseGame() / resumeGame() available");

initMqtt();

async function runLoop(): Promise<void> {
    await agentLoop();
    setTimeout(runLoop, POLL_DELAY_MS);
}

runLoop();
export { };
