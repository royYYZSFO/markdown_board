# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Meticulous Board is a single-user local priority board backed by a single markdown file (`Board.md`) in an Obsidian vault. It runs as a Python HTTP server serving a single-page HTML app at `http://localhost:7783`. The markdown file IS the database — edit it in Obsidian or in the web UI, both stay in sync.

## Running the App

```bash
# Start the server (runs on port 7783)
python3 server.py

# Or use the shell script
bash start.command

# Stop
bash stop-server.command
```

No build step, no package manager, no dependencies beyond Python 3 stdlib and a browser.

## Architecture

**Frontend (`index.html`):** Single HTML file containing all CSS, HTML, and JavaScript. No frameworks, no external JS libraries. Font loaded from Google Fonts CDN (Noto Sans).

**Backend (`server.py`):** Python stdlib HTTP server. Parses and serializes `Board.md`, serves the frontend, provides JSON API.

**`Board.md`:** Single markdown file in the Obsidian vault. Contains pillars, team members, and cards organized by column (Now, Next Up, Waiting, Done).

### Board.md Format

```markdown
# Meticulous Board

## Pillars
- 📦 Delivery Excellence | #1565C0 | Every customer receives their machine without friction

## Team
- Roy | RY | #F0380F

## Functions
- fulfillment | Fulfillment / Shipping | #00695C

## Now
- **Resolve Spanish customs import block** [high] @Roy #fulfillment >Delivery Excellence [[Meticulous/Shipping/Spain]]
  Coordinate with freight forwarder on HS codes and VAT documentation.

## Next Up
- **Shopify store optimization pass** [low] #website >Growth

## Waiting
## Done
```

**Card line format:** `- **Title** [priority] @Owner #function >Pillar [[link]]`
- All tokens after title are optional, any order
- Indented lines below a card = note text
- Defaults: `[medium]`, no owner, no function, no pillar

### Data Flow

```
User action → mutate global state (cards/owners/pillars arrays)
            → renderAll() / renderKanban() → DOM update
            → scheduleSave() → debounced PUT /api/board → Board.md
```

State lives in global JS variables. Persistence is the Board.md file via the server API. Saves are automatic and debounced (300ms). External changes (Obsidian edits) are detected by mtime polling every 3 seconds.

### Server API

| Endpoint     | Method | Purpose                                    |
|--------------|--------|--------------------------------------------|
| `/`          | GET    | Serve index.html                           |
| `/ping`      | GET    | Health check (returns vault + file info)   |
| `/api/board` | GET    | Parse Board.md → JSON (includes mtime)     |
| `/api/board` | PUT    | Receive JSON → serialize to Board.md       |
| `/config`    | GET    | Return vault path + board file config      |
| `/config`    | POST   | Update config.json                         |

### Key Data Models

**In-browser (frontend):**
- **Card:** `{id, title, note, fn, ownerId, col, priority, pillarId, link}` — IDs are ephemeral (regenerated on each load)
- **Owner:** `{id, name, initials, color}` — IDs prefixed with `o`
- **Pillar:** `{id, name, desc, icon, color}` — IDs prefixed with `p`

**On-disk (Board.md):** Name-based references (`@Roy`, `>Delivery Excellence`, `#fulfillment`). No IDs stored.

### Filtering

Four independent filter axes compose via AND logic: pillar, function (`fn`), owner, priority. Filter state held in globals `activePillar`, `activeFn`, `activeOwner`, `activePri` (default `'all'`).

## Conventions

- CSS classes: kebab-case (`.pane-header`, `.col-now`)
- JS functions: camelCase (`saveCard()`, `scheduleSave()`)
- No classes/constructors — functional style with global state
- Function-specific CSS is injected dynamically via `injectFunctionCSS()` using `fn-{key}` and `dot-{key}` patterns
- Card IDs are numeric (ephemeral), owner IDs `o{n}`, pillar IDs `p{n}`
- All CSS uses `--border-radius: 0px` (sharp corners by design)
- Functions are defined in the `## Functions` section of Board.md (key | label | color), auto-detected from card #tags if not declared
- Atomic file writes via temp file + `os.replace()`
