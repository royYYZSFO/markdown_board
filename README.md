# Meticulous Board

A local priority board that syncs cards to your Obsidian vault as `.md` files.

## Setup (5 minutes)

### 1. Place this folder
Move `Meticulous Board` to somewhere permanent, e.g.:
```
~/Documents/Meticulous Board/
```

### 2. Edit config.json
Open `config.json` and set your Obsidian vault path:
```json
{
  "vault_path": "/Users/yourname/Documents/Obsidian",
  "folder": "Meticulous/Cards"
}
```

### 3. Make the scripts executable (one-time)
Open Terminal, paste and run:
```bash
chmod +x ~/Documents/Meticulous\ Board/server.py
```

### 4. Launch the board
Double-click `Start Meticulous Board.applescript` in Script Editor and click Run.
(Or: open the .applescript file → File → Export as Application to make it double-clickable forever.)

The board opens at http://localhost:7783 in your browser.

## Daily use
- **Double-click** `Start Meticulous Board.applescript` to launch
- **↑ Sync** button in the header pushes all cards to Obsidian as `.md` files
- **Settings** lets you change vault path and manually sync
- All changes **auto-save** in your browser (localStorage) between sessions
- The server runs quietly in the background; stop it with `Stop Meticulous Board.applescript`

## Obsidian card format
Each card becomes a note like:
```markdown
---
id: 1
title: "Resolve Spanish customs import block"
function: fulfillment
owner: Roy
column: now
priority: high
pillar: Delivery Excellence
obsidian_link: [[Meticulous/Shipping/Spain]]
updated: 2026-02-20T10:30:00
---

Coordinate with freight forwarder on HS codes and VAT documentation.
```

You can query these with Obsidian Dataview, tag them, link them — they're real notes.
