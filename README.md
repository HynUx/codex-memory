<div align="center">
  <h1>🧠 Codex Memory</h1>
  <p><strong>Persistent, evolving memory for AI agents</strong></p>
  <p>SQLite-backed · Zero external dependencies · Auto-evolution · Obsidian-compatible export</p>

  <p>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
    <img src="https://img.shields.io/badge/tests-88%20passing-brightgreen" alt="Tests">
    <img src="https://img.shields.io/badge/dependencies-0-important" alt="Zero dependencies">
  </p>
</div>

---

**Codex Memory** gives AI agents a persistent, cross-session memory. It ingests scattered learning records, organizes them into a structured knowledge base, and evolves that knowledge as new information arrives — all without external services.

```bash
# Record → Evolve → Load — the core loop
python3 scripts/memory/main.py add --type tip --content "Learned about SQLite WAL mode"
python3 scripts/memory/main.py evolve
python3 scripts/memory/main.py load
```

---

## Why Codex Memory?

AI agents learn new things every session — user preferences, architecture decisions, bug workarounds, workflow tips. Without a persistent memory, this knowledge is lost on session end. Cloud memory services introduce latency, cost, and external dependencies.

Codex Memory solves this with a **zero-dependency, file-based approach**:

- **1 file to run** – `main.py` uses only Python stdlib (`sqlite3`, `hashlib`, `fcntl`)
- **1 directory for all data** – `~/.codex/memory/` contains everything
- **No services, no APIs, no configuration** – clone and run

---

## Features

| Feature | What it does |
|---------|-------------|
| 🗂️ **Persistent SQLite storage** | WAL-mode database survives crashes and powers concurrent access |
| 🔍 **Full-text search** | FTS5 indexes every record for instant keyword search |
| 🧬 **Knowledge evolution** | `evolve` consolidates scattered records into a structured `project-context.md` |
| 🔄 **Auto-evolution** | Unmerged records ≥ 20 → automatic `evolve` on `add` |
| ✏️ **Correction propagation** | Edit or delete any record; next `evolve` propagates the change |
| 📦 **Versioned rollback** | Every `evolve` creates a backup in `.backup/v{N}.bak` |
| 📚 **Obsidian-compatible export** | `export` generates standalone `.md` files with YAML frontmatter |
| 🔌 **Extensible semantic search** | Optional ONNX vector embeddings for semantic retrieval |
| 🔒 **Concurrent-safe** | WAL + `fcntl` file lock allow multiple agents to write safely |

---

## Quick Start

```bash
# 1. Get the code
git clone https://github.com/HynUx/codex-memory.git
cd codex-memory

# 2. Initialize (creates ~/.codex/memory/ and memory.db)
python3 scripts/memory/main.py status

# 3. Record your first memory
python3 scripts/memory/main.py add --type tip --content "Codex Memory uses SQLite WAL for crash safety" --topics '["architecture"]'

# 4. Evolve into structured knowledge
python3 scripts/memory/main.py evolve

# 5. Load context (call at session start)
python3 scripts/memory/main.py load
```

**That's it.** No `pip install`, no API keys, no config files.

---

## Installation Options

### As a standalone CLI

```bash
git clone https://github.com/HynUx/codex-memory.git
cd codex-memory

# Optional: add a shell alias
echo 'alias memory="python3 $(pwd)/scripts/memory/main.py"' >> ~/.zshrc
source ~/.zshrc
memory status
```

### Via pip (once published)

```bash
pip install git+https://github.com/HynUx/codex-memory.git
memory status
```

### As a Codex Skill

Copy `SKILL.md` to your Codex skills directory or reference it from your project prompt.

---

## Command Reference

| Command | Purpose | Example |
|---------|---------|---------|
| `add` | Record a learning | `memory add --type workflow --content "text" --topics '["tag"]'` |
| `search` | Search memories | `memory search "WAL" --limit 10` |
| `list` | Browse all | `memory list` |
| `delete` | Soft-delete | `memory delete 5` |
| `update` | Edit a record | `memory update 5 --content "new text"` |
| `evolve` | Consolidate knowledge | `memory evolve` |
| `load` | Load session context | `memory load` |
| `export` | Export to Obsidian vault | `memory export --dir /path/to/vault` |
| `status` | Health dashboard | `memory status` |
| `vec` | Vector index management | `memory vec status` |
| `migrate` | Import legacy data | `memory migrate` |

For detailed docs: `memory <command> --help`.

---

## How Evolution Works

The core idea is simple: **scattered records → consolidated knowledge → repeat.**

```
  add (record a learning)
    │
    ├── SHA256 de‑dup check
    ├── INSERT + FTS5 sync
    └──≥20 unmerged? → evolve()
                          │
                          ├── lock (fcntl)
                          ├── capture unmerged + corrected records
                          ├── backup → .backup/v{N}.bak
                          ├── rewrite project-context.md
                          ├── tag consolidated_seq
                          └── unlock
```

### Correction loop

When you edit or delete a record that was already consolidated, the system increments `correction_count`. The next `evolve` re-processes it with a `[user_correction]` or `[user_deletion]` tag. Corrections propagate to every future evolve.

### Versioning

Each evolve run generates a numbered backup (`.backup/v1.bak`, `.backup/v2.bak`, ...). The `project-context.md` header includes a version comment:

```html
<!-- evolve_seq: 3 -->
```

`load` detects stale versions and warns you.

---

## Architecture

### Data layout

```
~/.codex/memory/
├── memory.db              # SQLite (WAL mode)
│   ├── entries             # All records + soft‑deletes + correction counts
│   ├── entries_fts         # FTS5 full‑text index (trigger‑synced)
│   ├── entries_vec         # Optional vector embeddings
│   └── system              # Runtime state (evolve_seq, counters)
├── config.toml             # User config (optional)
├── profile.md              # User profile (hand‑edited)
├── project-context.md      # evolve output
├── .lock                   # File lock
├── .backup/                # Pre‑evolve snapshot
└── export/                 # export output
```

### Storage design

| Layer | Technology | Role |
|-------|-----------|------|
| Primary storage | SQLite (WAL) | ACID transactions, crash recovery |
| Keyword search | FTS5 (`unicode61`) | Full‑text index on `content` + `topics` |
| Semantic search | Cosine similarity (optional) | ONNX embeddings in `entries_vec` |
| Structured output | Markdown | `project-context.md`, `export/*.md` |
| Locking | `fcntl.flock` | Serialize concurrent `evolve` across processes |

**No external services. No API calls. No third-party packages.**

---

## Project Status

All 11 CLI commands are production-ready. `vec enable` and `vec rebuild` are stubs awaiting ONNX model integration.

```
Ran 88 tests in 0.188s
OK
```

---

## Contributing

Pull requests are welcome. For major changes, open an issue first to discuss.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Add tests — coverage matters
4. Run `python3 -m unittest discover -s tests -p "*.py"`
5. Commit with clear messages
6. Push and open a PR

---

## License

[MIT](LICENSE)

---

## Maintainer

**HynUx** · [GitHub](https://github.com/HynUx) · SK.Hynux@gmail.com
