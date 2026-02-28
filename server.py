#!/usr/bin/env python3
"""
Meticulous Board — Single-file Obsidian Board Server
Runs locally on port 7783. Reads/writes a single Board.md file in your Obsidian vault.
"""

import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PORT = 7783
DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian"
DEFAULT_BOARD_FILE = "Meticulous/Board.md"

# Load .env.local if present (key=value, supports quotes, ignores comments)
_env_path = Path(__file__).parent / ".env.local"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

CONFIG_PATH = Path(__file__).parent / "config.json"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
            return (
                Path(cfg.get("vault_path", str(DEFAULT_VAULT))),
                cfg.get("board_file", DEFAULT_BOARD_FILE),
            )
    return DEFAULT_VAULT, DEFAULT_BOARD_FILE


def board_path():
    vault, board_file = load_config()
    return vault / board_file


# ─── Markdown Parser ───────────────────────────────────────────


def parse_board(text):
    """Parse Board.md into a JSON-friendly dict."""
    pillars = []
    owners = []
    functions = []
    columns = {"now": [], "next": [], "waiting": [], "done": []}

    section = None
    current_card = None
    col_key = None

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()

        # Detect section headers
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            # Flush any in-progress card
            if current_card and col_key:
                columns[col_key].append(current_card)
                current_card = None

            if heading == "pillars":
                section = "pillars"
            elif heading == "team":
                section = "team"
            elif heading == "functions":
                section = "functions"
            elif heading in ("now",):
                section = "cards"
                col_key = "now"
            elif heading in ("next up", "next"):
                section = "cards"
                col_key = "next"
            elif heading in ("waiting",):
                section = "cards"
                col_key = "waiting"
            elif heading in ("done",):
                section = "cards"
                col_key = "done"
            else:
                section = None
            continue

        # Skip top-level heading and blank lines at section level
        if line.startswith("# "):
            continue

        # ── Pillars section ──
        if section == "pillars" and line.startswith("- "):
            pillar = parse_pillar_line(line[2:])
            if pillar:
                pillars.append(pillar)
            continue

        # ── Team section ──
        if section == "team" and line.startswith("- "):
            owner = parse_owner_line(line[2:])
            if owner:
                owners.append(owner)
            continue

        # ── Functions section ──
        if section == "functions" and line.startswith("- "):
            func = parse_function_line(line[2:])
            if func:
                functions.append(func)
            continue

        # ── Cards section ──
        if section == "cards" and col_key:
            if line.startswith("- "):
                # Flush previous card
                if current_card:
                    columns[col_key].append(current_card)
                current_card = parse_card_line(line[2:])
            elif current_card and (line.startswith("  ") or line.startswith("\t")):
                # Indented continuation
                note_line = line.strip()
                if note_line:
                    if note_line.startswith(">> ") and not current_card.get("nextAction"):
                        current_card["nextAction"] = note_line[3:]
                    elif current_card.get("note"):
                        current_card["note"] += "\n" + note_line
                    else:
                        current_card["note"] = note_line
            elif line.strip() == "" and current_card:
                # Blank line inside a card's note block — keep going
                pass
            continue

    # Flush last card
    if current_card and col_key:
        columns[col_key].append(current_card)

    return {
        "pillars": pillars,
        "owners": owners,
        "functions": functions,
        "columns": columns,
    }


def parse_pillar_line(text):
    """Parse: 📦 Delivery Excellence | #1565C0 | description"""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        return None
    name_part = parts[0]
    color = parts[1] if len(parts) >= 2 else "#1F1F1F"
    desc = parts[2] if len(parts) >= 3 else ""

    # Split icon from name: first char(s) may be emoji
    # Find first non-emoji-like character boundary
    icon = ""
    name = name_part
    if name_part:
        # Grab leading emoji (could be multi-codepoint)
        m = re.match(r"^(\S+)\s+(.*)", name_part)
        if m:
            icon = m.group(1)
            name = m.group(2)

    return {"icon": icon, "name": name, "color": color, "desc": desc}


def parse_owner_line(text):
    """Parse: Roy | RY | #F0380F"""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        return None
    return {
        "name": parts[0],
        "initials": parts[1],
        "color": parts[2] if len(parts) >= 3 else "#1F1F1F",
    }


def parse_function_line(text):
    """Parse: finops | Financial & Ops Plan | #B8A050"""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        return None
    return {
        "key": parts[0],
        "label": parts[1],
        "color": parts[2] if len(parts) >= 3 else "#8A8A88",
    }


def parse_card_line(text):
    """Parse: **Title** [priority] @Owner #function >Pillar [[link]]"""
    card = {"title": "", "priority": "medium", "owner": "", "fn": "", "pillar": "", "link": "", "note": "", "due": "", "nextAction": "", "movedAt": ""}

    # Extract ^YYYY-MM-DD movedAt date
    m = re.search(r"\^(\d{4}-\d{2}-\d{2})", text)
    if m:
        card["movedAt"] = m.group(1)
        text = text[: m.start()] + text[m.end() :]

    # Extract !YYYY-MM-DD due date
    m = re.search(r"!(\d{4}-\d{2}-\d{2})", text)
    if m:
        card["due"] = m.group(1)
        text = text[: m.start()] + text[m.end() :]

    # Extract [[link]]
    m = re.search(r"\[\[(.+?)\]\]", text)
    if m:
        card["link"] = "[[" + m.group(1) + "]]"
        text = text[: m.start()] + text[m.end() :]

    # Extract [priority]
    m = re.search(r"\[(high|medium|low)\]", text, re.IGNORECASE)
    if m:
        card["priority"] = m.group(1).lower()
        text = text[: m.start()] + text[m.end() :]

    # Extract @Owner
    m = re.search(r"@(\S+(?:\s+\S+)*?)(?=\s+[#>@\[]|$)", text)
    if m:
        card["owner"] = m.group(1).strip()
        text = text[: m.start()] + text[m.end() :]

    # Extract #function
    m = re.search(r"#(\S+)", text)
    if m:
        card["fn"] = m.group(1)
        text = text[: m.start()] + text[m.end() :]

    # Extract >Pillar (everything after > until ** or end of string)
    m = re.search(r">([^*]+)", text)
    if m:
        card["pillar"] = m.group(1).strip()
        text = text[: m.start()] + text[m.end() :]

    # Extract **Title**
    m = re.search(r"\*\*(.+?)\*\*", text)
    if m:
        card["title"] = m.group(1).strip()
    else:
        # Fallback: use whatever remains as title
        card["title"] = text.strip().strip("-").strip()

    return card


# ─── Markdown Serializer ──────────────────────────────────────


def serialize_board(data):
    """Serialize board data dict back to Board.md markdown."""
    lines = ["# Meticulous Board", ""]

    # Pillars
    lines.append("## Pillars")
    for p in data.get("pillars", []):
        desc_part = f" | {p['desc']}" if p.get("desc") else ""
        lines.append(f"- {p.get('icon', '🎯')} {p['name']} | {p.get('color', '#1F1F1F')}{desc_part}")
    lines.append("")

    # Team
    lines.append("## Team")
    for o in data.get("owners", []):
        lines.append(f"- {o['name']} | {o['initials']} | {o.get('color', '#1F1F1F')}")
    lines.append("")

    # Functions
    lines.append("## Functions")
    for f in data.get("functions", []):
        lines.append(f"- {f['key']} | {f['label']} | {f.get('color', '#8A8A88')}")
    lines.append("")

    # Columns
    col_headings = [("now", "Now"), ("next", "Next Up"), ("waiting", "Waiting"), ("done", "Done")]
    columns = data.get("columns", {})
    for col_key, col_title in col_headings:
        cards = columns.get(col_key, [])
        lines.append(f"## {col_title}")
        for c in cards:
            lines.append(serialize_card(c))
            if c.get("nextAction"):
                lines.append(f"  >> {c['nextAction']}")
            if c.get("note"):
                for note_line in c["note"].split("\n"):
                    lines.append(f"  {note_line}")
        lines.append("")

    return "\n".join(lines)


def serialize_card(card):
    """Serialize a single card to its markdown line."""
    parts = [f"- **{card['title']}**"]

    if card.get("priority") and card["priority"] != "medium":
        parts.append(f"[{card['priority']}]")

    if card.get("owner"):
        parts.append(f"@{card['owner']}")

    if card.get("fn"):
        parts.append(f"#{card['fn']}")

    if card.get("pillar"):
        parts.append(f">{card['pillar']}")

    if card.get("due"):
        parts.append(f"!{card['due']}")

    if card.get("movedAt"):
        parts.append(f"^{card['movedAt']}")

    if card.get("link"):
        link = card["link"]
        if not link.startswith("[["):
            link = f"[[{link}]]"
        parts.append(link)

    return " ".join(parts)


# ─── File I/O ──────────────────────────────────────────────────


def read_board():
    """Read and parse the board file. Returns (data_dict, mtime)."""
    fp = board_path()
    if not fp.exists():
        return None, 0
    text = fp.read_text(encoding="utf-8")
    data = parse_board(text)
    mtime = fp.stat().st_mtime
    return data, mtime


def write_board(data):
    """Atomically write the board file."""
    fp = board_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    text = serialize_board(data)
    # Atomic write: write to temp file then replace
    fd, tmp = tempfile.mkstemp(dir=str(fp.parent), suffix=".tmp")
    closed = False
    try:
        os.write(fd, text.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp, str(fp))
    except Exception:
        if not closed:
            try: os.close(fd)
            except OSError: pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return fp.stat().st_mtime


def create_default_board():
    """Create a default Board.md if none exists."""
    data = {
        "pillars": [
            {"icon": "📦", "name": "Delivery Excellence", "color": "#1565C0", "desc": "Every customer receives their machine without friction"},
            {"icon": "🤝", "name": "Customer Trust", "color": "#2E7D32", "desc": "Support is a competitive moat"},
            {"icon": "☕", "name": "Community", "color": "#6A1B9A", "desc": "Build the definitive social platform for lever espresso"},
            {"icon": "📈", "name": "Growth", "color": "#F0380F", "desc": "Scale production, expand markets, convert momentum into revenue"},
        ],
        "owners": [
            {"name": "Roy", "initials": "RY", "color": "#F0380F"},
        ],
        "functions": [],
        "columns": {
            "now": [
                {"title": "Resolve Spanish customs import block", "priority": "high", "owner": "Roy", "fn": "fulfillment", "pillar": "Delivery Excellence", "link": "[[Meticulous/Shipping/Spain]]", "note": "Coordinate with freight forwarder on HS codes and VAT documentation."},
            ],
            "next": [
                {"title": "Shopify store optimization pass", "priority": "low", "owner": "", "fn": "website", "pillar": "Growth", "link": "", "note": ""},
            ],
            "waiting": [
                {"title": "CE / FCC certifications for new markets", "priority": "high", "owner": "", "fn": "manufacturing", "pillar": "Growth", "link": "", "note": "Awaiting test lab results from supplier."},
            ],
            "done": [
                {"title": "Kickstarter backer surveys closed", "priority": "low", "owner": "Roy", "fn": "operations", "pillar": "Growth", "link": "", "note": ""},
            ],
        },
    }
    write_board(data)
    return data


# ─── Brief Creation ───────────────────────────────────────────


def slugify(text):
    """Convert title to a filename-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:60]


def next_brief_number():
    """Count existing brief_*.md files and return next number."""
    vault, _ = load_config()
    briefs_dir = vault / "Meticulous" / "Briefs"
    if not briefs_dir.exists():
        return 1
    existing = sorted(briefs_dir.glob("brief_*.md"))
    if not existing:
        return 1
    # Extract highest number from existing files
    highest = 0
    for f in existing:
        m = re.match(r"brief_(\d+)", f.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def render_brief_template(card_data):
    """Render the brief markdown template with card metadata."""
    title = card_data.get("title", "Untitled")
    owner = card_data.get("owner", "")
    fn = card_data.get("fn", "")
    priority = card_data.get("priority", "medium")
    due = card_data.get("due", "")
    note = card_data.get("note", "")
    today = date.today().isoformat()

    # Look up function label — try reading from current board data
    fn_display = fn.replace("-", " ").replace("_", " ").title() if fn else ""
    try:
        board_data, _ = read_board()
        if board_data:
            for f in board_data.get("functions", []):
                if f.get("key") == fn:
                    fn_display = f.get("label", fn_display)
                    break
    except Exception:
        pass

    lines = [
        f"# {title}",
        "",
        "## Objective",
        "_What needs to happen and why._",
        "",
        "## Context",
    ]
    if owner:
        lines.append(f"- **Owner:** {owner}")
    if fn_display:
        lines.append(f"- **Function:** {fn_display}")
    lines.append(f"- **Priority:** {priority.capitalize()}")
    if due:
        lines.append(f"- **Due:** {due}")
    lines.append(f"- **Created:** {today}")
    lines += [
        "",
        "## Current Situation",
        "_What is the current state? What has already been tried or decided?_",
        "",
        "## Actions Required",
        "- [ ] ",
        "- [ ] ",
        "- [ ] ",
        "",
        "## Deliverables",
        "_List what needs to be produced (email draft, document, ticket, etc.):_",
        "- ",
        "",
        "## Done When",
        "- ",
        "",
        "## Notes",
    ]
    if note:
        lines.append(note)
    else:
        lines.append("")
    lines.append("")
    return "\n".join(lines)


def write_brief(card_data):
    """Create a brief file and return the wiki link path."""
    vault, _ = load_config()
    briefs_dir = vault / "Meticulous" / "Briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)

    num = next_brief_number()
    slug = slugify(card_data.get("title", "untitled"))
    filename = f"brief_{num:02d}_{slug}.md"
    filepath = briefs_dir / filename

    content = render_brief_template(card_data)

    # Atomic write
    fd, tmp = tempfile.mkstemp(dir=str(briefs_dir), suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp, str(filepath))
    except Exception:
        if not closed:
            try: os.close(fd)
            except OSError: pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    # Return wiki link without .md extension
    wiki_path = f"Meticulous/Briefs/{filepath.stem}"
    return f"[[{wiki_path}]]"


# ─── AI Assist ─────────────────────────────────────────────────



def read_brief_content(link):
    """Read a brief file from the vault given a [[wiki link]]."""
    vault, _ = load_config()
    inner = link.strip().strip("[").strip("]")
    if not inner:
        return None
    filepath = vault / (inner + ".md")
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return None


def build_system_prompt(card, brief_content, fn_label, pillar_desc):
    """Build the system prompt for AI chat from card context."""
    if not fn_label:
        fn_label = card.get("fn", "")

    # Calculate age in column
    age = ""
    moved = card.get("movedAt", "")
    if moved:
        try:
            from datetime import datetime
            moved_date = datetime.strptime(moved, "%Y-%m-%d").date()
            age = str((date.today() - moved_date).days)
        except Exception:
            pass

    lines = [
        "You are an AI assistant helping action a specific task on a priority board.",
        "",
        "## Card",
        f"- Title: {card.get('title', '')}",
        f"- Column: {card.get('col', '')} (current status)",
        f"- Priority: {card.get('priority', '')}",
        f"- Owner: {card.get('owner', '')}",
        f"- Due: {card.get('due', '') or 'Not set'}",
        f"- Function: {fn_label}",
        f"- Pillar: {card.get('pillar', '')}",
        f"- Next Action: {card.get('nextAction', '') or 'Not set'}",
        f"- Note: {card.get('note', '') or 'None'}",
    ]
    if age:
        lines.append(f"- In current column: {age} days")

    if pillar_desc:
        lines.append("")
        lines.append("## Pillar")
        lines.append(pillar_desc)

    lines.append("")
    lines.append("## Brief")
    lines.append(brief_content if brief_content else "No brief linked to this card.")

    lines.append("")
    lines.append("---")
    lines.append("Help the user take action on this task. You can:")
    lines.append("- Draft emails, messages, or communications")
    lines.append("- Write PRDs, project plans, or briefs")
    lines.append("- Break down the task into concrete action steps")
    lines.append("- Research questions and suggest approaches")
    lines.append("- Draft any document the user needs")
    lines.append("")
    lines.append("Be direct and produce ready-to-use outputs. When drafting communications,")
    lines.append("use a professional but human tone.")

    return "\n".join(lines)


def save_vault_file(rel_path, content):
    """Save content as a .md file in the vault."""
    vault, _ = load_config()
    filepath = vault / rel_path
    filepath.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    fd, tmp = tempfile.mkstemp(dir=str(filepath.parent), suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp, str(filepath))
    except Exception:
        if not closed:
            try: os.close(fd)
            except OSError: pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return str(filepath)


# ─── HTTP Handler ──────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/ping":
            vault, board_file = load_config()
            self.send_json({"ok": True, "vault": str(vault), "board_file": board_file, "hasApiKey": bool(ANTHROPIC_API_KEY)})

        elif parsed.path == "/api/board":
            data, mtime = read_board()
            if data is None:
                data = create_default_board()
                mtime = board_path().stat().st_mtime
            self.send_json({"board": data, "mtime": mtime})

        elif parsed.path == "/api/brief-content":
            qs = parse_qs(parsed.query)
            link = qs.get("link", [""])[0]
            content = read_brief_content(link) if link else None
            self.send_json({"content": content or "", "found": content is not None})

        elif parsed.path == "/config":
            vault, board_file = load_config()
            self.send_json({"vault": str(vault), "board_file": board_file})

        else:
            html_path = Path(__file__).parent / "index.html"
            if html_path.exists():
                content = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_json({"error": "index.html not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if parsed.path == "/api/board":
            try:
                data = json.loads(body)
            except Exception:
                self.send_json({"error": "Invalid JSON"}, 400)
                return
            try:
                mtime = write_board(data)
                self.send_json({"ok": True, "mtime": mtime})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if parsed.path == "/api/brief":
            try:
                data = json.loads(body)
            except Exception:
                self.send_json({"error": "Invalid JSON"}, 400)
                return
            try:
                link = write_brief(data)
                self.send_json({"ok": True, "link": link})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/ai/chat":
            if not ANTHROPIC_API_KEY:
                self.send_json({"error": "No API key configured"}, 403)
                return
            try:
                data = json.loads(body)
            except Exception:
                self.send_json({"error": "Invalid JSON"}, 400)
                return
            try:
                self._stream_ai_chat(data)
            except Exception as e:
                # If headers haven't been sent yet, send error JSON
                try:
                    self.send_json({"error": str(e)}, 500)
                except Exception:
                    pass

        elif parsed.path == "/api/vault/save":
            try:
                data = json.loads(body)
            except Exception:
                self.send_json({"error": "Invalid JSON"}, 400)
                return
            try:
                title = data.get("title", "untitled")
                content = data.get("content", "")
                # Use same brief numbering/naming as Create Brief
                vault, _ = load_config()
                briefs_dir = vault / "Meticulous" / "Briefs"
                briefs_dir.mkdir(parents=True, exist_ok=True)
                num = next_brief_number()
                slug = slugify(title)
                filename = f"brief_{num:02d}_{slug}.md"
                filepath = briefs_dir / filename
                # Atomic write
                fd, tmp = tempfile.mkstemp(dir=str(briefs_dir), suffix=".tmp")
                closed = False
                try:
                    os.write(fd, content.encode("utf-8"))
                    os.close(fd)
                    closed = True
                    os.replace(tmp, str(filepath))
                except Exception:
                    if not closed:
                        try: os.close(fd)
                        except OSError: pass
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                    raise
                wiki_path = f"Meticulous/Briefs/{filepath.stem}"
                link = f"[[{wiki_path}]]"
                self.send_json({"ok": True, "link": link})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif parsed.path == "/config":
            try:
                data = json.loads(body)
            except Exception:
                self.send_json({"error": "Invalid JSON"}, 400)
                return
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  [config] Saved: {data}")
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "Not found"}, 404)

    def _stream_ai_chat(self, data):
        """Handle streaming AI chat via Claude API."""
        messages = data.get("messages", [])
        card = data.get("card", {})
        brief_content = data.get("briefContent", "")
        fn_label = data.get("fnLabel", "")
        pillar_desc = data.get("pillarDesc", "")

        system_prompt = build_system_prompt(card, brief_content, fn_label, pillar_desc)

        api_body = json.dumps({
            "model": CLAUDE_MODEL,
            "max_tokens": 4096,
            "stream": True,
            "system": system_prompt,
            "messages": messages,
        }).encode("utf-8")

        req = Request(CLAUDE_API_URL, data=api_body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", ANTHROPIC_API_KEY)
        req.add_header("anthropic-version", "2023-06-01")

        # Send SSE headers to client
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            resp = urlopen(req, timeout=60)
            buf = ""
            stream_done = False
            while not stream_done:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        event_data = line[6:]
                        if event_data.strip() == "[DONE]":
                            stream_done = True
                            break
                        try:
                            evt = json.loads(event_data)
                            evt_type = evt.get("type", "")
                            if evt_type == "content_block_delta":
                                delta = evt.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    sse = f"data: {json.dumps({'text': text})}\n\n"
                                    self.wfile.write(sse.encode("utf-8"))
                                    self.wfile.flush()
                            elif evt_type == "message_stop":
                                stream_done = True
                                break
                            elif evt_type == "error":
                                err_msg = evt.get("error", {}).get("message", "Unknown error")
                                sse = f"data: {json.dumps({'error': err_msg})}\n\n"
                                self.wfile.write(sse.encode("utf-8"))
                                self.wfile.flush()
                                stream_done = True
                                break
                        except json.JSONDecodeError:
                            pass
            resp.close()
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", str(e))
            except Exception:
                err_msg = f"API error {e.code}: {err_body[:200]}"
            sse = f"data: {json.dumps({'error': err_msg})}\n\n"
            self.wfile.write(sse.encode("utf-8"))
            self.wfile.flush()
        except Exception as e:
            sse = f"data: {json.dumps({'error': str(e)})}\n\n"
            self.wfile.write(sse.encode("utf-8"))
            self.wfile.flush()

        # Send done signal
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    vault, board_file = load_config()
    fp = vault / board_file
    print(f"\n  Meticulous Board Server")
    print(f"  URL:    http://localhost:{PORT}")
    print(f"  Vault:  {vault}")
    print(f"  Board:  {board_file}")
    print(f"  File:   {fp}")
    if ANTHROPIC_API_KEY:
        print(f"  AI:     Enabled (API key set)")
    else:
        print(f"  AI:     Disabled (set ANTHROPIC_API_KEY to enable)")
    print(f"  Ready. Open http://localhost:{PORT} in your browser.\n")
    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
