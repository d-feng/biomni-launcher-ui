import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import subprocess
import sys
import os
import re
import json
import uuid
import datetime
from pathlib import Path
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

HOME = Path.home()
LOG_DIR = HOME / "biomni_logs"
DATA_SOURCES_FILE = HOME / "biomni_data_sources.json"
PROJECTS_FILE = HOME / "biomni_projects.json"
MEMORY_DB_DIR = HOME / "biomni_memory"
DEFAULT_DATA_DIR = str(HOME / "biomni_data")
DEFAULT_GENE = "IFNG"
DEFAULT_TIMEOUT = 1200
MEMORY_TOP_K = 3
MEMORY_SUMMARY_WORDS = 150

MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-4-5-20251001",
    "gpt-4o",
    "gpt-4-turbo",
    "gemini-2.0-flash",
]

PROMPTS = {
    "Protein Expression": (
        "Analyze protein expression changes for {GENE} across protein datasets. "
        "Identify significant expression differences, associated conditions, and potential biological implications."
    ),
    "DEG & Pathway": (
        "Perform differential expression analysis for {GENE} and identify enriched pathways, "
        "GO terms, and KEGG annotations."
    ),
    "Target Characterization": (
        "Characterize {GENE} by: summarizing key findings from literature including known functions and therapeutic relevance; "
        "identifying protein-protein interaction partners and mapping downstream signaling pathways; "
        "summarizing GWAS findings and disease associations across genomic databases."
    ),
    "scRNA-seq Full Pipeline": (
        "Download single-cell RNA-seq data for {GENE} from public repositories, preprocess, "
        "create an h5ad AnnData dataframe with cell metadata and gene expression matrix, "
        "then perform cell type annotation focusing on {GENE} expression patterns across cell clusters."
    ),
}


# ── Projects ──────────────────────────────────────────────────────────────────
def load_projects():
    if PROJECTS_FILE.exists():
        try:
            return json.loads(PROJECTS_FILE.read_text())
        except Exception:
            pass
    return ["Default"]


def save_projects(projects):
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))


# ── Data sources ──────────────────────────────────────────────────────────────
def load_data_sources():
    if DATA_SOURCES_FILE.exists():
        try:
            return json.loads(DATA_SOURCES_FILE.read_text())
        except Exception:
            pass
    return []


def save_data_sources(sources):
    DATA_SOURCES_FILE.write_text(json.dumps(sources, indent=2))


# ── Memory (per-project ChromaDB) ─────────────────────────────────────────────
def _safe_collection_name(project):
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", project).strip("_")
    return f"proj_{name}"[:63] or "proj_default"


def _get_collection(project):
    import chromadb
    MEMORY_DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(MEMORY_DB_DIR))
    return client.get_or_create_collection(_safe_collection_name(project))


def _summarize(text, max_words=MEMORY_SUMMARY_WORDS):
    words = str(text).split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def _extract_solution(text):
    m = re.search(r"<solution>(.*?)</solution>", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # fallback: last === RESULT === block
    m = re.search(r"=== RESULT ===(.*?)$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return _summarize(text)


def memory_save_pending(project, gene, preset, model, prompt, full_result, log_path):
    """Save a run as 'pending' — shown in review, not yet used for injection."""
    try:
        col = _get_collection(project)
        summary = _summarize(full_result)
        solution = _extract_solution(full_result)
        run_id = str(uuid.uuid4())
        timestamp = datetime.datetime.now().isoformat()
        col.add(
            ids=[run_id],
            documents=[f"{prompt}\n{summary}"],
            metadatas=[{
                "gene": gene, "preset": preset, "model": model,
                "prompt": prompt, "summary": summary, "solution": solution,
                "log_path": str(log_path), "timestamp": timestamp,
                "status": "pending", "notes": "",
            }],
        )
        return run_id
    except Exception as e:
        print(f"[Memory] Save failed: {e}")
        return None


def memory_keep(project, run_id, notes=""):
    """Mark a pending run as kept — eligible for auto-inject."""
    try:
        col = _get_collection(project)
        result = col.get(ids=[run_id])
        if not result["ids"]:
            return
        meta = result["metadatas"][0]
        meta["status"] = "kept"
        meta["notes"] = notes
        col.update(ids=[run_id], metadatas=[meta])
    except Exception as e:
        print(f"[Memory] Keep failed: {e}")


def memory_delete(project, run_id):
    try:
        col = _get_collection(project)
        col.delete(ids=[run_id])
    except Exception as e:
        print(f"[Memory] Delete failed: {e}")


def memory_search(project, query, top_k=MEMORY_TOP_K):
    """Search only 'kept' entries."""
    try:
        col = _get_collection(project)
        total = col.count()
        if total == 0:
            return []
        results = col.query(
            query_texts=[query],
            n_results=min(top_k * 3, total),
            where={"status": "kept"},
        )
        entries = []
        for i, meta in enumerate(results["metadatas"][0]):
            entries.append({
                "id": results["ids"][0][i],
                "gene": meta.get("gene", ""),
                "preset": meta.get("preset", ""),
                "model": meta.get("model", ""),
                "prompt": meta.get("prompt", ""),
                "summary": meta.get("summary", ""),
                "solution": meta.get("solution", ""),
                "log_path": meta.get("log_path", ""),
                "timestamp": meta.get("timestamp", ""),
                "notes": meta.get("notes", ""),
            })
            if len(entries) >= top_k:
                break
        return entries
    except Exception as e:
        print(f"[Memory] Search failed: {e}")
        return []


def memory_list_all(project):
    """Return all kept entries for Results Manager."""
    try:
        col = _get_collection(project)
        if col.count() == 0:
            return []
        results = col.get(where={"status": "kept"})
        entries = []
        for i, run_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            entries.append({
                "id": run_id,
                "gene": meta.get("gene", ""),
                "preset": meta.get("preset", ""),
                "model": meta.get("model", ""),
                "prompt": meta.get("prompt", ""),
                "summary": meta.get("summary", ""),
                "solution": meta.get("solution", ""),
                "log_path": meta.get("log_path", ""),
                "timestamp": meta.get("timestamp", ""),
                "notes": meta.get("notes", ""),
            })
        return sorted(entries, key=lambda x: x["timestamp"], reverse=True)
    except Exception as e:
        print(f"[Memory] List failed: {e}")
        return []


# ── Main App ──────────────────────────────────────────────────────────────────
class BiomniLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Biomni Launcher")
        self.resizable(True, True)
        self.minsize(1050, 780)

        self.data_sources = load_data_sources()
        self.projects = load_projects()
        self._agent_thread = None
        self._stop_flag = threading.Event()
        self._memory_entries = []
        self._memory_include_vars = []
        self._pending_run_id = None

        self._build_ui()
        self._refresh_data_source_list()

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Config bar
        cfg = ttk.LabelFrame(self, text="Configuration", padding=6)
        cfg.pack(fill="x", padx=8, pady=(8, 4))

        # Row 0: project + model + data dir
        ttk.Label(cfg, text="Project:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.project_var = tk.StringVar(value=self.projects[0])
        self.project_cb = ttk.Combobox(cfg, textvariable=self.project_var,
                                       values=self.projects + ["＋ New Project…"],
                                       width=18, state="readonly")
        self.project_cb.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.project_cb.bind("<<ComboboxSelected>>", self._on_project_change)

        ttk.Label(cfg, text="Model:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.model_var = tk.StringVar(value=MODELS[0])
        ttk.Combobox(cfg, textvariable=self.model_var, values=MODELS,
                     width=28, state="readonly").grid(row=0, column=3, sticky="w", padx=(0, 12))

        ttk.Label(cfg, text="Data dir:").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.data_dir_var = tk.StringVar(value=DEFAULT_DATA_DIR)
        ttk.Entry(cfg, textvariable=self.data_dir_var, width=28).grid(row=0, column=5, sticky="w", padx=(0, 4))
        ttk.Button(cfg, text="Browse…", command=self._browse_data_dir).grid(row=0, column=6, sticky="w")

        # Row 1: timeout + skip datalake + auto-memory
        ttk.Label(cfg, text="Timeout (s):").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(4, 0))
        self.timeout_var = tk.IntVar(value=DEFAULT_TIMEOUT)
        ttk.Spinbox(cfg, from_=60, to=7200, increment=60, textvariable=self.timeout_var,
                    width=8).grid(row=1, column=1, sticky="w", pady=(4, 0))

        self.skip_datalake_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="Skip data lake", variable=self.skip_datalake_var).grid(
            row=1, column=2, sticky="w", pady=(4, 0))

        self.auto_memory_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text="Auto-include memory", variable=self.auto_memory_var).grid(
            row=1, column=3, sticky="w", pady=(4, 0))

        # Middle pane
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        # Left: prompt
        prompt_frame = ttk.LabelFrame(mid, text="Prompt", padding=6)
        prompt_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        prompt_frame.rowconfigure(2, weight=1)
        prompt_frame.columnconfigure(1, weight=1)

        ttk.Label(prompt_frame, text="Preset:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.preset_var = tk.StringVar(value=list(PROMPTS.keys())[0])
        preset_cb = ttk.Combobox(prompt_frame, textvariable=self.preset_var,
                                  values=list(PROMPTS.keys()), state="readonly", width=30)
        preset_cb.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        preset_cb.bind("<<ComboboxSelected>>", self._on_preset_change)

        ttk.Label(prompt_frame, text="Gene:").grid(row=1, column=0, sticky="w", padx=(0, 4))
        self.gene_var = tk.StringVar(value=DEFAULT_GENE)
        ttk.Entry(prompt_frame, textvariable=self.gene_var, width=16).grid(
            row=1, column=1, sticky="w", pady=(0, 4))
        self.gene_var.trace_add("write", self._on_gene_change)

        ttk.Label(prompt_frame, text="Prompt:").grid(row=2, column=0, sticky="nw", padx=(0, 4))
        self.prompt_text = tk.Text(prompt_frame, wrap="word", height=10)
        self.prompt_text.grid(row=2, column=1, sticky="nsew")
        scroll_p = ttk.Scrollbar(prompt_frame, command=self.prompt_text.yview)
        scroll_p.grid(row=2, column=2, sticky="ns")
        self.prompt_text.configure(yscrollcommand=scroll_p.set)
        self._fill_prompt()

        # Right column
        right = ttk.Frame(mid)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=2)
        right.columnconfigure(0, weight=1)

        # Data Sources
        ds_frame = ttk.LabelFrame(right, text="Data Sources", padding=6)
        ds_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        ds_frame.rowconfigure(0, weight=1)
        ds_frame.columnconfigure(0, weight=1)

        cols = ("Name", "Type", "Value")
        self.ds_tree = ttk.Treeview(ds_frame, columns=cols, show="headings",
                                    selectmode="browse", height=4)
        for col in cols:
            self.ds_tree.heading(col, text=col)
        self.ds_tree.column("Name", width=80)
        self.ds_tree.column("Type", width=45)
        self.ds_tree.column("Value", width=150)
        self.ds_tree.grid(row=0, column=0, columnspan=3, sticky="nsew")
        ds_scroll = ttk.Scrollbar(ds_frame, command=self.ds_tree.yview)
        ds_scroll.grid(row=0, column=3, sticky="ns")
        self.ds_tree.configure(yscrollcommand=ds_scroll.set)
        self.ds_tree.bind("<ButtonRelease-1>", self._on_ds_click)

        ds_btn = ttk.Frame(ds_frame)
        ds_btn.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        ttk.Button(ds_btn, text="Add Path", command=self._add_path).pack(side="left", padx=2)
        ttk.Button(ds_btn, text="Add URL", command=self._add_url).pack(side="left", padx=2)
        ttk.Button(ds_btn, text="Remove", command=self._remove_ds).pack(side="left", padx=2)
        ttk.Label(ds_frame, text="Click to append to prompt", foreground="gray").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # Memory panel
        mem_frame = ttk.LabelFrame(right, text="Memory (Project: kept results)", padding=6)
        mem_frame.grid(row=1, column=0, sticky="nsew")
        mem_frame.rowconfigure(1, weight=1)
        mem_frame.columnconfigure(0, weight=1)

        search_row = ttk.Frame(mem_frame)
        search_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        search_row.columnconfigure(0, weight=1)
        self.mem_search_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.mem_search_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(search_row, text="Search", command=self._memory_search).grid(row=0, column=1)
        ttk.Button(search_row, text="Recent", command=self._memory_recent).grid(
            row=0, column=2, padx=(4, 0))

        self.mem_canvas = tk.Canvas(mem_frame, highlightthickness=0)
        self.mem_canvas.grid(row=1, column=0, sticky="nsew")
        mem_scroll = ttk.Scrollbar(mem_frame, orient="vertical", command=self.mem_canvas.yview)
        mem_scroll.grid(row=1, column=1, sticky="ns")
        self.mem_canvas.configure(yscrollcommand=mem_scroll.set)
        self.mem_inner = ttk.Frame(self.mem_canvas)
        self.mem_canvas.create_window((0, 0), window=self.mem_inner, anchor="nw")
        self.mem_inner.bind("<Configure>", lambda e: self.mem_canvas.configure(
            scrollregion=self.mem_canvas.bbox("all")))

        ttk.Label(mem_frame, text="Checked entries injected into prompt",
                  foreground="gray").grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # Output
        out_frame = ttk.LabelFrame(self, text="Output", padding=6)
        out_frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        out_frame.rowconfigure(0, weight=1)
        out_frame.columnconfigure(0, weight=1)

        self.output_text = tk.Text(out_frame, wrap="word", state="disabled",
                                   bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.output_text.grid(row=0, column=0, sticky="nsew")
        out_scroll = ttk.Scrollbar(out_frame, command=self.output_text.yview)
        out_scroll.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=out_scroll.set)

        # Action bar
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill="x", padx=8, pady=(0, 8))
        self.start_btn = ttk.Button(btn_bar, text="▶  Start Workflow", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(btn_bar, text="■  Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left")
        ttk.Button(btn_bar, text="Clear Output", command=self._clear_output).pack(side="left", padx=8)
        ttk.Button(btn_bar, text="Results Manager", command=self._open_results_manager).pack(side="left")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(btn_bar, textvariable=self.status_var, foreground="gray").pack(side="right")

    # ── Project ────────────────────────────────────────────────────────────────
    def _on_project_change(self, _event=None):
        val = self.project_var.get()
        if val == "＋ New Project…":
            name = simpledialog.askstring("New Project", "Enter project name:")
            if name and name.strip():
                name = name.strip()
                if name not in self.projects:
                    self.projects.append(name)
                    save_projects(self.projects)
                self.project_var.set(name)
                self.project_cb["values"] = self.projects + ["＋ New Project…"]
            else:
                self.project_var.set(self.projects[0])
        self._render_memory_entries([])

    # ── Prompt ─────────────────────────────────────────────────────────────────
    def _fill_prompt(self):
        template = PROMPTS[self.preset_var.get()]
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", template.replace("{GENE}", gene))

    def _on_preset_change(self, _event=None):
        self._fill_prompt()

    def _on_gene_change(self, *_args):
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        template = PROMPTS[self.preset_var.get()]
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", template.replace("{GENE}", gene))

    # ── Data Sources ───────────────────────────────────────────────────────────
    def _refresh_data_source_list(self):
        self.ds_tree.delete(*self.ds_tree.get_children())
        for entry in self.data_sources:
            self.ds_tree.insert("", "end", values=(entry["name"], entry["type"], entry["value"]))

    def _on_ds_click(self, _event):
        sel = self.ds_tree.selection()
        if sel:
            self.prompt_text.insert("end", f" {self.ds_tree.item(sel[0], 'values')[2]}")

    def _add_path(self):
        path = filedialog.askdirectory(title="Select data directory")
        if not path:
            return
        name = simpledialog.askstring("Name", "Short name:", initialvalue=Path(path).name)
        if not name:
            return
        self.data_sources.append({"name": name, "type": "PATH", "value": path})
        save_data_sources(self.data_sources)
        self._refresh_data_source_list()

    def _add_url(self):
        url = simpledialog.askstring("URL", "Enter data URL:")
        if not url:
            return
        name = simpledialog.askstring("Name", "Short name:")
        if not name:
            return
        self.data_sources.append({"name": name, "type": "URL", "value": url})
        save_data_sources(self.data_sources)
        self._refresh_data_source_list()

    def _remove_ds(self):
        sel = self.ds_tree.selection()
        if not sel:
            return
        self.data_sources.pop(self.ds_tree.index(sel[0]))
        save_data_sources(self.data_sources)
        self._refresh_data_source_list()

    def _browse_data_dir(self):
        path = filedialog.askdirectory(title="Select Biomni data directory")
        if path:
            self.data_dir_var.set(path)

    # ── Memory panel ───────────────────────────────────────────────────────────
    def _memory_search(self):
        query = self.mem_search_var.get().strip()
        if query:
            self._render_memory_entries(memory_search(self.project_var.get(), query))

    def _memory_recent(self):
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        self._render_memory_entries(memory_search(self.project_var.get(), gene))

    def _render_memory_entries(self, entries):
        for w in self.mem_inner.winfo_children():
            w.destroy()
        self._memory_entries = entries
        self._memory_include_vars = []

        if not entries:
            ttk.Label(self.mem_inner, text="No kept results found.", foreground="gray").pack(
                anchor="w", pady=4)
            return

        for i, entry in enumerate(entries):
            var = tk.BooleanVar(value=True)
            self._memory_include_vars.append(var)

            row = ttk.Frame(self.mem_inner, relief="groove", padding=4)
            row.pack(fill="x", pady=2, padx=2)

            header = ttk.Frame(row)
            header.pack(fill="x")
            ttk.Checkbutton(header, variable=var).pack(side="left")
            lbl = ttk.Label(
                header,
                text=f"{entry['gene']}  |  {entry['preset']}  |  {entry['timestamp'][:16]}",
                font=("Consolas", 8, "bold"), cursor="hand2"
            )
            lbl.pack(side="left", fill="x", expand=True)

            summary_lbl = ttk.Label(row, text=entry["summary"][:120] + "…",
                                    wraplength=260, foreground="gray", font=("Consolas", 8))
            summary_lbl.pack(anchor="w", pady=(2, 0))

            for w in (lbl, summary_lbl):
                w.bind("<Button-1>", lambda e, ent=entry: self._show_memory_detail(ent))

    def _show_memory_detail(self, entry):
        win = tk.Toplevel(self)
        win.title(f"{entry['gene']} / {entry['preset']}")
        win.geometry("720x520")
        txt = tk.Text(win, wrap="word", font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0",
            f"Gene: {entry['gene']}\nPreset: {entry['preset']}\nModel: {entry['model']}\n"
            f"Timestamp: {entry['timestamp']}\nLog: {entry['log_path']}\n"
            f"Notes: {entry['notes']}\n\n"
            f"{'='*60}\nSOLUTION:\n{'='*60}\n{entry['solution']}\n\n"
            f"{'='*60}\nSUMMARY:\n{'='*60}\n{entry['summary']}"
        )
        txt.configure(state="disabled")

    def _build_memory_context(self):
        lines = []
        for i, var in enumerate(self._memory_include_vars):
            if var.get() and i < len(self._memory_entries):
                e = self._memory_entries[i]
                lines.append(
                    f"[Past analysis — {e['gene']} / {e['preset']} / {e['timestamp'][:16]}]:\n{e['summary']}"
                )
        if not lines:
            return ""
        return "=== RELEVANT PAST ANALYSES ===\n" + "\n\n".join(lines) + "\n=== END PAST ANALYSES ===\n\n"

    # ── Output ─────────────────────────────────────────────────────────────────
    def _append_output(self, text):
        self.output_text.configure(state="normal")
        self.output_text.insert("end", text)
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def _clear_output(self):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    # ── Workflow ───────────────────────────────────────────────────────────────
    def _start(self):
        base_prompt = self.prompt_text.get("1.0", "end-1c").strip()
        if not base_prompt:
            messagebox.showwarning("Empty prompt", "Please enter a prompt.")
            return

        project = self.project_var.get()

        # Auto-search memory before running
        if self.auto_memory_var.get():
            gene = self.gene_var.get().strip() or DEFAULT_GENE
            query = f"{gene} {base_prompt[:120]}"
            entries = memory_search(project, query)
            self._render_memory_entries(entries)
            if entries:
                self._append_output(
                    f"[Memory] Found {len(entries)} relevant past result(s) for project '{project}'. "
                    f"Checked entries will be injected.\n"
                )

        memory_context = self._build_memory_context() if self.auto_memory_var.get() else ""
        prompt = memory_context + base_prompt

        self._stop_flag.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Running…")
        self._clear_output()

        if memory_context:
            self._append_output(f"[Memory] Injecting past context into prompt.\n{'='*60}\n")

        self._agent_thread = threading.Thread(
            target=self._run_workflow, args=(prompt, base_prompt), daemon=True)
        self._agent_thread.start()

    def _stop(self):
        self._stop_flag.set()
        self.status_var.set("Stopping…")

    def _run_workflow(self, prompt, base_prompt):
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        preset = self.preset_var.get()
        model = self.model_var.get()
        project = self.project_var.get()
        data_dir = self.data_dir_var.get()
        timeout = self.timeout_var.get()
        skip_datalake = self.skip_datalake_var.get()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"biomni_{gene}_{timestamp}.txt"

        script = f"""
import sys, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from biomni.agent import A1
from biomni.config import default_config

default_config.timeout_seconds = {timeout}

kwargs = dict(path={repr(data_dir)}, llm={repr(model)})
if {repr(skip_datalake)}:
    kwargs['expected_data_lake_files'] = []

agent = A1(**kwargs)
result = agent.go({repr(prompt)})
print("\\n=== RESULT ===")
print(result)
"""

        self._append_output(f"[{timestamp}] Project: {project}\n")
        self._append_output(f"Gene: {gene} | Preset: {preset} | Model: {model}\n")
        self._append_output(f"Log: {log_path}\n{'='*60}\n")

        full_result = []
        completed = False

        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                log_file.write(
                    f"Biomni Launcher — {timestamp}\nProject: {project}\n"
                    f"Gene: {gene}\nPreset: {preset}\nModel: {model}\n"
                    f"Prompt:\n{base_prompt}\n\n{'='*60}\n\n"
                )
                proc = subprocess.Popen(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
                for line in proc.stdout:
                    if self._stop_flag.is_set():
                        proc.terminate()
                        self._append_output("\n[Stopped by user]\n")
                        log_file.write("\n[Stopped by user]\n")
                        break
                    self._append_output(line)
                    log_file.write(line)
                    full_result.append(line)

                proc.wait()
                if proc.returncode == 0:
                    completed = True
                status = "Completed" if completed else f"Exited with code {proc.returncode}"
                self._append_output(f"\n[{status}]\n")
                log_file.write(f"\n[{status}]\n")

        except Exception as e:
            self._append_output(f"\n[ERROR] {e}\n")

        if completed:
            full_text = "".join(full_result)
            run_id = memory_save_pending(
                project, gene, preset, model, base_prompt, full_text, log_path)
            self._pending_run_id = run_id
            self.after(0, lambda: self._show_review_popup(project, run_id, full_text))

        self.after(0, self._on_workflow_done)

    def _on_workflow_done(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("Ready")

    # ── Results Review popup ───────────────────────────────────────────────────
    def _show_review_popup(self, project, run_id, full_text):
        if not run_id:
            return
        solution = _extract_solution(full_text)

        win = tk.Toplevel(self)
        win.title("Results Review — Keep or Delete?")
        win.geometry("750x550")
        win.grab_set()

        ttk.Label(win, text="Review the result below. Keep to save to project memory (used in future runs). Delete to discard.",
                  wraplength=700).pack(padx=10, pady=(10, 4))

        txt = tk.Text(win, wrap="word", font=("Consolas", 9), bg="#f9f9f9")
        txt.pack(fill="both", expand=True, padx=10, pady=4)
        txt.insert("1.0", solution)
        txt.configure(state="disabled")

        notes_frame = ttk.Frame(win)
        notes_frame.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(notes_frame, text="Notes (optional):").pack(side="left", padx=(0, 6))
        notes_var = tk.StringVar()
        ttk.Entry(notes_frame, textvariable=notes_var, width=50).pack(side="left", fill="x", expand=True)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=(0, 10))

        def on_keep():
            memory_keep(project, run_id, notes_var.get().strip())
            self._append_output(f"[Memory] Result kept in project '{project}'.\n")
            win.destroy()

        def on_delete():
            memory_delete(project, run_id)
            self._append_output(f"[Memory] Result discarded.\n")
            win.destroy()

        ttk.Button(btn_frame, text="Keep  (save to memory)", command=on_keep).pack(side="left", padx=12)
        ttk.Button(btn_frame, text="Delete  (discard)", command=on_delete).pack(side="left", padx=12)

    # ── Results Manager ────────────────────────────────────────────────────────
    def _open_results_manager(self):
        project = self.project_var.get()
        win = tk.Toplevel(self)
        win.title(f"Results Manager — {project}")
        win.geometry("900x550")

        top = ttk.Frame(win)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Filter gene:").pack(side="left")
        filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=filter_var, width=14).pack(side="left", padx=4)
        ttk.Button(top, text="Filter", command=lambda: _refresh(filter_var.get())).pack(side="left")
        ttk.Button(top, text="Show All", command=lambda: _refresh("")).pack(side="left", padx=4)

        cols = ("Gene", "Preset", "Model", "Timestamp", "Notes")
        tree = ttk.Treeview(win, columns=cols, show="headings", selectmode="browse")
        for col in cols:
            tree.heading(col, text=col)
        tree.column("Gene", width=80)
        tree.column("Preset", width=160)
        tree.column("Model", width=160)
        tree.column("Timestamp", width=140)
        tree.column("Notes", width=200)
        tree.pack(fill="both", expand=True, padx=8, pady=4)

        scroll = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)

        all_entries = []

        def _refresh(gene_filter=""):
            tree.delete(*tree.get_children())
            all_entries.clear()
            entries = memory_list_all(project)
            for e in entries:
                if gene_filter and gene_filter.upper() not in e["gene"].upper():
                    continue
                all_entries.append(e)
                tree.insert("", "end", values=(
                    e["gene"], e["preset"], e["model"],
                    e["timestamp"][:16], e["notes"]
                ))

        _refresh()

        def on_view():
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            self._show_memory_detail(all_entries[idx])

        def on_delete():
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            entry = all_entries[idx]
            if messagebox.askyesno("Delete", f"Delete result for {entry['gene']} / {entry['preset']}?"):
                memory_delete(project, entry["id"])
                _refresh(filter_var.get())

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=(0, 8))
        ttk.Button(btn_row, text="View Summary", command=on_view).pack(side="left", padx=8)
        ttk.Button(btn_row, text="Delete Selected", command=on_delete).pack(side="left", padx=8)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BiomniLauncher()
    app.mainloop()
