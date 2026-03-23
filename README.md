# OmniLink Tetris Demo

A Pygame Tetris game controlled by a local AI engine, orchestrated through
the OmniLink platform via **tool calling**.  The AI agent never sees the game —
it simply calls the `make_move` tool, which runs a local controller that
evaluates every possible piece placement and sends the optimal move in real time.

This keeps API credit usage to a minimum (one call to kick off the game).

This demo showcases four core OmniLink features:

| Feature | How it is used |
|---|---|
| **Tool Calling** | Agent calls `make_move` — the platform forwards execution to the local AI controller |
| **Commands** | Agent outputs `Command: stop_game` to end the game early |
| **Short-Term Memory** | Game state (score, lines, level, lives) is saved periodically so the agent can answer questions |
| **Chat API** | The agent can be asked about the game state at any time from the OmniLink UI |

---

## Benchmark Results

| Metric | Value |
|---|---|
| **Final Score** | 705,902 (hi-score) |
| **Level** | 35 |
| **Lines Cleared** | 341 |
| **Lives Used** | 15/15 |
| **Play Time** | 10m 19s |
| **API Calls** | 1 kick-off + ~20 reviews (1 per 30s) |
| **AI Strategy** | Pierre Dellacherie evaluation with macro-action batching |

The Tetris agent is the highest-scoring benchmark in the suite, demonstrating
that the tool-calling architecture can sustain high-speed continuous control
with minimal API usage.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.9 or later |
| OmniKey | Sign up at https://www.omnilink-agents.com |

Python packages:

```
pip install pygame requests
```

The OmniLink Python client (`omnilink-lib`) must be available on your
`PYTHONPATH`.  The script auto-adds `../../omnilink-lib/src` to `sys.path`,
so the default repo layout works out of the box.

---

## Quick Start

You need **two terminals**.

### Step 1 — Start the game server (Terminal 1)

```bash
cd omnilink-tetris
python server_wrapper.py
```

This launches:
- The **Pygame window** — the Tetris game itself
- An **HTTP API** on **http://localhost:5001** for state polling and action sending

The game will appear in a **TITLE** screen, waiting for the agent to start it.

### Step 2 — Add your OmniKey

Open `tetris_link/play_tetris.py` in a text editor and replace the `OMNI_KEY`
value with your own key:

```python
OMNI_KEY = "olink_YOUR_KEY_HERE"
```

You can find your OmniKey in the OmniLink dashboard at
https://www.omnilink-agents.com after signing up.

### Step 3 — Run the AI agent (Terminal 2)

```bash
cd tetris_link
python -u play_tetris.py
```

The `-u` flag disables output buffering so you see events printed in real time.

The script will:
1. Create (or update) a `tetris-agent` profile on OmniLink
2. Ask the agent to call the `make_move` tool (one API call)
3. Send a `/start` command to begin the game
4. Enter the AI control loop — placing pieces automatically

### Step 4 — Watch and interact

- **Pygame window** — Watch the AI place Tetris pieces in real time.
- **Terminal output** — See score updates, line clears, level changes, and
  AI placement decisions as they happen.
- **OmniLink UI** — Log in at https://www.omnilink-agents.com, find the
  `tetris-agent` profile, and chat with it.  Ask things like *"What's the
  score?"* or *"How many lines have been cleared?"* — the agent has the
  current game state in memory.
- **Stop the game** — Type *"stop the game"* in the OmniLink UI.  The agent
  will output `Command: stop_game`, which the script detects and ends the
  session.

### Step 5 — Review the results

When the game ends (either all 15 lives lost, agent stops, or you close the
window), the script will:
1. Print a final game summary (score, level, lines, lives)
2. Save the final state to OmniLink memory
3. Ask the agent for a final analysis of the game

---

## Configuration

All settings are at the top of `tetris_link/play_tetris.py`:

```python
BASE_URL      = "https://www.omnilink-agents.com"  # OmniLink platform URL
OMNI_KEY      = "olink_..."                         # Your OmniKey
AGENT_NAME    = "tetris-agent"                      # Agent profile name
ENGINE        = "g2-engine"                         # AI engine (see below)
POLL_INTERVAL = 0.0        # Seconds between game state polls (0 = max speed)
MEMORY_EVERY  = 10         # Save state to memory every N seconds
ASK_EVERY     = 30         # Agent reviews the game every N seconds
USE_MACRO     = True       # Send full action sequences (recommended)
```

### Available Engines

| Engine | Model |
|---|---|
| `g1-engine` | Gemini |
| `g2-engine` | GPT-5 |
| `g3-engine` | Grok |
| `g4-engine` | Claude |

### Macro vs Single-Action Mode

| Mode | Setting | Behaviour |
|---|---|---|
| **Macro** (default) | `USE_MACRO = True` | Computes the full action sequence (rotate + translate + drop) and sends it as a batch. Survives high gravity speeds. |
| **Single-action** | `USE_MACRO = False` | Sends one action per poll (ROTATE, LEFT, RIGHT, or DROP). Simpler but may struggle at high gravity. |

### Free Plan Limits

- **1 agent profile** — the script creates/updates a `tetris-agent` profile.
- **Monthly credit cap** — the tool-calling architecture minimises API usage:
  1 call to kick off + 1 review call every 30 seconds of gameplay.

---

## How It Works

### Architecture

```
+---------------------+       +--------------------+       +------------------+
|   OmniLink Cloud    |       |  server_wrapper.py |       |   Pygame Window  |
|   Chat + Memory +   |       |  localhost:5001    |       |   Tetris game    |
|   Tool Calling      |       |  HTTP API + Game   |       |                  |
+---------------------+       +--------------------+       +------------------+
        ^                            ^       |
        |  REST API                  |       | Pygame renders
        v                            |  HTTP | directly
+---------------------+             |       |
|  play_tetris.py      |-------------+       |
|  + tetris_engine.py  |  GET /data (poll state)
|  + tetris_api.py     |  POST /callback (send actions)
|  + OmniLinkClient    |  POST /start (begin game)
+---------------------+
```

### Control Loop

Tetris runs as a **continuous control loop**:

```
1. Kick off            One API call: agent calls Tool: make_move
                       This confirms the agent is connected. The local
                       AI controller then takes over.

2. Start game          tetris_api.start_game() POSTs to /start to
                       transition from the TITLE screen to active play.

3. Poll state          tetris_api.get_state() fetches the game state
                       via GET /data: board grid, current piece (type,
                       rotation, x, y), next piece, score, lines, level,
                       lives, play time.

4. Evaluate & act      tetris_engine.get_macro_actions() (macro mode):
                       - For every (rotation x column) placement:
                         simulate hard-drop on a board copy and score it
                       - Pick the best placement
                       - Generate full action sequence: ROTATE...LEFT/RIGHT...DROP
                       - Send as a single batch via POST /callback

5. Send actions        tetris_api.send_actions() POSTs the action batch
                       to the game server, which queues them for execution
                       at 0.04s intervals.

6. Check for UI stop   Every MEMORY_EVERY seconds, reads the agent's
                       memory via get_memory(). If the user typed "stop"
                       in the OmniLink UI, the agent's response contains
                       "Command: stop_game" — the script exits.

7. Save to memory      set_memory() writes score, lines, level, lives,
                       current/next piece, and board fill so the agent
                       can answer questions from the UI.

8. Agent review        Every ASK_EVERY seconds, the script asks the
   (periodic)          agent to review. The agent either:
                       - Calls Tool: make_move → game continues
                       - Outputs Command: stop_game → game ends

9. Sleep & repeat      Waits POLL_INTERVAL seconds, back to step 3.
```

### AI Strategy (Pierre Dellacherie Evaluation)

For every possible placement of the current piece (all rotations x all columns):

1. Simulate a hard-drop onto a copy of the board
2. Score the resulting board with four weighted metrics:

| Metric | Weight | Goal |
|---|---|---|
| **Lines cleared** | +500 | Maximise line clears |
| **Holes** | -400 | Minimise empty cells with filled cells above |
| **Aggregate height** | -30 | Keep the board low |
| **Bumpiness** | -50 | Keep column heights even |

3. Pick the placement with the highest score
4. Generate the action sequence to reach that placement

### Stopping the Game

There are three ways the session can end:

| Method | How |
|---|---|
| **Game Over** | All 15 lives lost — the Pygame window shows GAMEOVER |
| **Agent review** | Every 30s the agent evaluates the game state and can output `Command: stop_game` |
| **User via OmniLink UI** | Type "stop the game" in the chat — the script detects it on the next memory check |

---

## Key Files

| File | Description |
|---|---|
| `tetris_link/play_tetris.py` | Main script — OmniLink integration, control loop, memory sync |
| `tetris_link/tetris_engine.py` | AI controller — Pierre Dellacherie evaluation, placement decisions |
| `tetris_link/tetris_api.py` | HTTP client for polling state, sending actions, and starting the game |
| `tetris.py` | Pygame game engine — piece physics, gravity, rendering, line clearing |
| `server_wrapper.py` | HTTP + MQTT bridge wrapping the Pygame game |

### Legacy TypeScript Agents

The repository also includes standalone TypeScript agents that connect directly
to the game server without OmniLink integration:

| File | Description |
|---|---|
| `agent.ts` | Basic single-action-per-poll agent |
| `advanced_agent.ts` | Macro-action batching agent for high-speed play |

These can be run with `npx ts-node agent.ts` but do not use the OmniLink
platform features (memory, tool calling, chat).

---

## Game Mechanics

| Parameter | Value |
|---|---|
| Board size | 10 columns x 20 rows |
| Pieces | I, O, T, S, Z, J, L (7-bag randomiser) |
| Lives | 15 |
| Gravity | Starts at 1.0s/drop, exponentially decreases to 0.05s floor |
| Scoring | Line clears: [0, 100, 300, 500, 800] x level; Hard drop: +2/cell |
| Level | Increases every 10 lines |
| Action rate | One queued action processed every 0.04 seconds |

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `429: Monthly usage limit exceeded` | OmniKey credits exhausted | Wait for monthly reset or upgrade plan |
| `403: PROFILE_LIMIT_REACHED` | Free plan allows only 1 profile | Reuse an existing profile name |
| `Connection refused` on port 5001 | Game server not running | Start `python server_wrapper.py` first |
| Game stuck on TITLE screen | Agent hasn't started the game | Make sure `play_tetris.py` is running |
| No output from `play_tetris.py` | Buffered stdout | Use `python -u` (unbuffered) |
| Stop from UI doesn't work | Checked between memory intervals | Try again — checked every 10 seconds |
| `ModuleNotFoundError: omnilink` | Python can't find the library | Ensure `omnilink-lib/src` is on your `PYTHONPATH` |
| `ModuleNotFoundError: pygame` | Pygame not installed | Run `pip install pygame` |
| Pieces pile up at high speed | Gravity outpaces poll rate | Use `USE_MACRO = True` (default) |
