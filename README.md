# Biomni Launcher UI

A Tkinter desktop UI to run [Biomni](https://github.com/snap-stanford/Biomni) agentic biomedical workflows without a web server. Features project-based memory with semantic search and result review.

## Requirements

- Python 3.11+
- NVIDIA GPU recommended (CPU-only also works)
- Anthropic API key (or OpenAI / Gemini key)

## Setup

### 1. Configure API key

Create a `.env` file in this folder:

```
ANTHROPIC_API_KEY=your_key_here
```

### 2. Create virtual environment

**Windows:**
```bat
setup_venv.bat
```

**Linux:**
```bash
chmod +x setup_venv.sh
./setup_venv.sh
```

This installs all dependencies (biomni, langgraph, chromadb, torch, pyarrow) into an isolated `venv/` folder.

## How to Run

**Windows:**
```bat
venv\Scripts\activate
python biomni_launcher.py
```

**Linux:**
```bash
source venv/bin/activate
python biomni_launcher.py
```

## Features

| Feature | Details |
|---------|---------|
| 4 preset prompts | Protein Expression, DEG & Pathway, Target Characterization, scRNA-seq Full Pipeline |
| Gene symbol field | Default `IFNG`, live substitution into prompt |
| Editable prompt | Freely edit before running |
| Model selector | Claude, GPT-4o, Gemini and more |
| Data directory | Browse to select Biomni data path |
| Timeout | Configurable in seconds (default 1200s) |
| Skip data lake | Checkbox to skip ~11GB download for testing |
| Data source manager | Add local paths or URLs, click to append to prompt |
| Live output | Scrollable terminal-style output panel |
| Log files | Saved to `~/biomni_logs/biomni_{GENE}_{timestamp}.txt` |
| Stop button | Terminate agent mid-run |
| Project memory | Isolated per-project semantic memory (ChromaDB) |
| Auto-include memory | Auto-searches and injects relevant past results before each run |
| Results Review | Keep or Delete popup after each run — only kept results used in future |
| Results Manager | Browse, filter, view, and delete kept results per project |

## Projects

Use the **Project** dropdown in the configuration bar to organize runs:

- Each project has its own isolated memory — no cross-contamination between projects
- Select an existing project or create a new one via **＋ New Project…**
- All memory search and injection is scoped to the active project

## Memory System

Memory is powered by [ChromaDB](https://www.trychroma.com/) with the `all-MiniLM-L6-v2` embedding model (downloaded once, ~79MB, cached at `~/.cache/chroma/`).

**How it works:**
1. Click **▶ Start Workflow** — memory auto-searches the current project for relevant past runs
2. Top 3 semantically similar kept results appear in the **Memory panel** with checkboxes pre-checked
3. Checked entries are injected into the prompt as context before the agent runs
4. After the run completes, a **Results Review** popup shows the extracted solution
5. Click **Keep** (saved to project memory, used in future runs) or **Delete** (discarded)

**Toggle auto-injection:** Use the **"Auto-include memory"** checkbox in the configuration bar to enable/disable injection without clearing results.

**Manual search:** Type a query in the Memory panel search bar and click **Search**, or click **Recent** to find results matching the current gene.

## Results Manager

Click **Results Manager** in the action bar to:
- View all kept results for the current project
- Filter by gene symbol
- View the full solution summary
- Delete entries

## Data Sources

Use the **Data Sources** panel to save frequently used datasets (local paths or URLs).
Click any entry to append it to the prompt text.
Sources are saved globally to `~/biomni_data_sources.json`.

## File Locations

| File | Path |
|------|------|
| Run logs | `~/biomni_logs/biomni_{GENE}_{timestamp}.txt` |
| Memory database | `~/biomni_memory/` |
| Data sources | `~/biomni_data_sources.json` |
| Projects list | `~/biomni_projects.json` |
