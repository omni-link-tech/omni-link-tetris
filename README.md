# OmniLink Tetris Base Project

This repository contains a full Pygame implementation of Tetris augmented with an advanced agent interaction architecture. The project is designed to provide both standard playable gameplay as well as external AI environment integration through HTTP REST endpoints and MQTT events.

## Features Added & Game Mechanics
- **Core Tetris Rules**: Standard rotational piece placement with soft and hard drops. Line-clearing tracks scores and levels based on traditional Tetris rules.
- **Lives System**: The game provides 15 lives. If a piece overlaps at the top (game over condition), a life is subtracted, the board is wiped, and play resumes, retaining your current time and score.
- **Time-based Difficulty**: As the game progresses (measured in active playtime seconds), the gravity drop speed exponentially decreases to become significantly harder over time. This makes the game much more challenging for standard agents as the drop rate out-scales their poll rate.
- **Macro-Action Array Architecture**: Instead of locking the API to one move per frame, the backend is capable of parsing queued "macro rules," instantly teleporting a falling piece to its destination without allowing gravity to interrupt its placement.

## Architecture & Components

The core architecture flows entirely around `server_wrapper.py`:

- **`tetris.py` (The Game Engine)**: A Pygame environment exposing the Tetris model. Holds the drawing logic while maintaining physical simulation loops for `dt` and external AI injections into `self.pending_actions`.

- **`server_wrapper.py` (Backend REST / MQTT Bridge)**: The server that connects the game client to the AI API endpoints.
  - **`GET /data` (Port 5001)**: Emits current JSON state of the board, active piece, next piece, score, lives, and time.
  - **`POST /callback` (Port 5001)**: Returns an array of game actions (`LEFT`, `RIGHT`, `ROTATE`, `DOWN`, `DROP`) directly into the engine's action queue.
  - **MQTT (`olink/commands`)**: Enables toggling pause states in real-time.
  - **MQTT (`olink/context`)**: Publishes summary telemetry data of the active game (score and level tracking).

- **`advanced_agent.ts`**: The hyper-speed intelligent agent written in Node TypeScript. It runs external to the game client, continuously polling the `/data` endpoint. It leverages a comprehensive Pierre Dellacherie algorithmic strategy by evaluating rotational holes, cumulative aggregate height, and col-bumpiness. When a new shape spawns, the agent pushes an array of pre-computed macro-actions directly to the HTTP POST endpoint.

- **`agent.ts`**: The basic algorithm implementation meant for standard line-by-line Tetris logic. Capable of evaluating shapes and emitting singular macro-actions, but severely struggles when the game's time-based difficulty scaling ramps the gravity beyond standard HTTP polling.

## How to Run

1. **Launch the Server & Game Environment**:
   Starting the HTTP Server and Pygame Client together:
   ```bash
   python server_wrapper.py
   ```
   At this point, the Tetris game screen will appear in an idle/waiting state to accept agent requests, or you can interact manually by pressing Space.

2. **Launch the Advanced Agent**:
   Transpile and fire up the Node isolated agent.
   ```bash
   npx ts-node advanced_agent.ts
   ```
   The agent will immediately link up and start processing game frames, passing full pathing matrices straight into the Tetris board.

*Note: All game states, high scores, pause logic, and piece behaviors are natively processed and synchronized between these components continuously.*
