import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import subprocess
import sys
import os
import json
import datetime
from pathlib import Path
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

HOME = Path.home()
LOG_DIR = HOME / "biomni_logs"
DATA_SOURCES_FILE = HOME / "biomni_data_sources.json"
DEFAULT_DATA_DIR = str(HOME / "biomni_data")
DEFAULT_GENE = "IFNG"
DEFAULT_TIMEOUT = 1200

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


# ── Data sources helpers ───────────────────────────────────────────────────────
def load_data_sources():
    if DATA_SOURCES_FILE.exists():
        try:
            return json.loads(DATA_SOURCES_FILE.read_text())
        except Exception:
            pass
    return []


def save_data_sources(sources):
    DATA_SOURCES_FILE.write_text(json.dumps(sources, indent=2))


# ── Main App ──────────────────────────────────────────────────────────────────
class BiomniLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Biomni Launcher")
        self.resizable(True, True)
        self.minsize(900, 700)

        self.data_sources = load_data_sources()
        self._agent_thread = None
        self._stop_flag = threading.Event()

        self._build_ui()
        self._refresh_data_source_list()

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        # Top config bar
        cfg = ttk.LabelFrame(self, text="Configuration", padding=6)
        cfg.pack(fill="x", padx=8, pady=(8, 4))

        # Row 0: model + data dir
        ttk.Label(cfg, text="Model:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.model_var = tk.StringVar(value=MODELS[0])
        ttk.Combobox(cfg, textvariable=self.model_var, values=MODELS, width=32, state="readonly").grid(
            row=0, column=1, sticky="w", padx=(0, 16)
        )

        ttk.Label(cfg, text="Data dir:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.data_dir_var = tk.StringVar(value=DEFAULT_DATA_DIR)
        ttk.Entry(cfg, textvariable=self.data_dir_var, width=36).grid(row=0, column=3, sticky="w", padx=(0, 4))
        ttk.Button(cfg, text="Browse…", command=self._browse_data_dir).grid(row=0, column=4, sticky="w")

        # Row 1: timeout + skip data lake
        ttk.Label(cfg, text="Timeout (s):").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(4, 0))
        self.timeout_var = tk.IntVar(value=DEFAULT_TIMEOUT)
        ttk.Spinbox(cfg, from_=60, to=7200, increment=60, textvariable=self.timeout_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(4, 0)
        )

        self.skip_datalake_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="Skip data lake download (faster testing)", variable=self.skip_datalake_var).grid(
            row=1, column=2, columnspan=3, sticky="w", pady=(4, 0)
        )

        # Middle pane: prompt + data sources side by side
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        # Left: prompt panel
        prompt_frame = ttk.LabelFrame(mid, text="Prompt", padding=6)
        prompt_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        prompt_frame.rowconfigure(2, weight=1)
        prompt_frame.columnconfigure(1, weight=1)

        ttk.Label(prompt_frame, text="Preset:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.preset_var = tk.StringVar(value=list(PROMPTS.keys())[0])
        preset_cb = ttk.Combobox(
            prompt_frame, textvariable=self.preset_var,
            values=list(PROMPTS.keys()), state="readonly", width=30
        )
        preset_cb.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        preset_cb.bind("<<ComboboxSelected>>", self._on_preset_change)

        ttk.Label(prompt_frame, text="Gene:").grid(row=1, column=0, sticky="w", padx=(0, 4))
        self.gene_var = tk.StringVar(value=DEFAULT_GENE)
        gene_entry = ttk.Entry(prompt_frame, textvariable=self.gene_var, width=16)
        gene_entry.grid(row=1, column=1, sticky="w", pady=(0, 4))
        self.gene_var.trace_add("write", self._on_gene_change)

        ttk.Label(prompt_frame, text="Prompt:").grid(row=2, column=0, sticky="nw", padx=(0, 4))
        self.prompt_text = tk.Text(prompt_frame, wrap="word", height=10)
        self.prompt_text.grid(row=2, column=1, sticky="nsew")
        scroll_p = ttk.Scrollbar(prompt_frame, command=self.prompt_text.yview)
        scroll_p.grid(row=2, column=2, sticky="ns")
        self.prompt_text.configure(yscrollcommand=scroll_p.set)

        # Initialise prompt text
        self._fill_prompt()

        # Right: data source manager
        ds_frame = ttk.LabelFrame(mid, text="Data Sources", padding=6)
        ds_frame.grid(row=0, column=1, sticky="nsew")
        ds_frame.rowconfigure(0, weight=1)
        ds_frame.columnconfigure(0, weight=1)

        cols = ("Name", "Type", "Value")
        self.ds_tree = ttk.Treeview(ds_frame, columns=cols, show="headings", selectmode="browse")
        for col in cols:
            self.ds_tree.heading(col, text=col)
        self.ds_tree.column("Name", width=90)
        self.ds_tree.column("Type", width=50)
        self.ds_tree.column("Value", width=160)
        self.ds_tree.grid(row=0, column=0, columnspan=3, sticky="nsew")
        ds_scroll = ttk.Scrollbar(ds_frame, command=self.ds_tree.yview)
        ds_scroll.grid(row=0, column=3, sticky="ns")
        self.ds_tree.configure(yscrollcommand=ds_scroll.set)
        self.ds_tree.bind("<ButtonRelease-1>", self._on_ds_click)

        btn_row = ttk.Frame(ds_frame)
        btn_row.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        ttk.Button(btn_row, text="Add Path", command=self._add_path).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Add URL", command=self._add_url).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Remove", command=self._remove_ds).pack(side="left", padx=2)

        ttk.Label(ds_frame, text="Click a row to append to prompt", foreground="gray").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(2, 0)
        )

        # Bottom: output
        out_frame = ttk.LabelFrame(self, text="Output", padding=6)
        out_frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))
        out_frame.rowconfigure(0, weight=1)
        out_frame.columnconfigure(0, weight=1)

        self.output_text = tk.Text(out_frame, wrap="word", state="disabled", bg="#1e1e1e", fg="#d4d4d4",
                                   font=("Consolas", 9))
        self.output_text.grid(row=0, column=0, sticky="nsew")
        out_scroll = ttk.Scrollbar(out_frame, command=self.output_text.yview)
        out_scroll.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=out_scroll.set)

        # Action buttons
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill="x", padx=8, pady=(0, 8))
        self.start_btn = ttk.Button(btn_bar, text="▶  Start Workflow", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(btn_bar, text="■  Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left")
        ttk.Button(btn_bar, text="Clear Output", command=self._clear_output).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(btn_bar, textvariable=self.status_var, foreground="gray").pack(side="right")

    # ── Prompt helpers ─────────────────────────────────────────────────────────
    def _fill_prompt(self):
        template = PROMPTS[self.preset_var.get()]
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", template.replace("{GENE}", gene))

    def _on_preset_change(self, _event=None):
        self._fill_prompt()

    def _on_gene_change(self, *_args):
        current = self.prompt_text.get("1.0", "end-1c")
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        # Replace any existing gene token (simple approach: reload template)
        template = PROMPTS[self.preset_var.get()]
        new_text = template.replace("{GENE}", gene)
        # Only update if prompt still matches a known template pattern
        # (preserves manual edits unless gene symbol changes)
        for name, tmpl in PROMPTS.items():
            for g in [gene, DEFAULT_GENE] + [g for g in [current]]:
                pass
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", new_text)

    # ── Data source manager ────────────────────────────────────────────────────
    def _refresh_data_source_list(self):
        self.ds_tree.delete(*self.ds_tree.get_children())
        for entry in self.data_sources:
            self.ds_tree.insert("", "end", values=(entry["name"], entry["type"], entry["value"]))

    def _on_ds_click(self, _event):
        sel = self.ds_tree.selection()
        if not sel:
            return
        values = self.ds_tree.item(sel[0], "values")
        value = values[2]
        self.prompt_text.insert("end", f" {value}")

    def _add_path(self):
        path = filedialog.askdirectory(title="Select data directory")
        if not path:
            return
        name = simpledialog.askstring("Name", "Enter a short name for this data source:", initialvalue=Path(path).name)
        if not name:
            return
        self.data_sources.append({"name": name, "type": "PATH", "value": path})
        save_data_sources(self.data_sources)
        self._refresh_data_source_list()

    def _add_url(self):
        url = simpledialog.askstring("URL", "Enter data URL:")
        if not url:
            return
        name = simpledialog.askstring("Name", "Enter a short name for this data source:")
        if not name:
            return
        self.data_sources.append({"name": name, "type": "URL", "value": url})
        save_data_sources(self.data_sources)
        self._refresh_data_source_list()

    def _remove_ds(self):
        sel = self.ds_tree.selection()
        if not sel:
            return
        idx = self.ds_tree.index(sel[0])
        self.data_sources.pop(idx)
        save_data_sources(self.data_sources)
        self._refresh_data_source_list()

    # ── Browse ─────────────────────────────────────────────────────────────────
    def _browse_data_dir(self):
        path = filedialog.askdirectory(title="Select Biomni data directory")
        if path:
            self.data_dir_var.set(path)

    # ── Output helpers ─────────────────────────────────────────────────────────
    def _append_output(self, text):
        self.output_text.configure(state="normal")
        self.output_text.insert("end", text)
        self.output_text.see("end")
        self.output_text.configure(state="disabled")

    def _clear_output(self):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    # ── Workflow execution ─────────────────────────────────────────────────────
    def _start(self):
        prompt = self.prompt_text.get("1.0", "end-1c").strip()
        if not prompt:
            messagebox.showwarning("Empty prompt", "Please enter a prompt before starting.")
            return

        self._stop_flag.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Running…")
        self._clear_output()

        self._agent_thread = threading.Thread(target=self._run_workflow, args=(prompt,), daemon=True)
        self._agent_thread.start()

    def _stop(self):
        self._stop_flag.set()
        self.status_var.set("Stopping…")

    def _run_workflow(self, prompt):
        gene = self.gene_var.get().strip() or DEFAULT_GENE
        model = self.model_var.get()
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

        self._append_output(f"[{timestamp}] Starting Biomni workflow\n")
        self._append_output(f"Gene: {gene} | Model: {model}\n")
        self._append_output(f"Log: {log_path}\n")
        self._append_output("=" * 60 + "\n")

        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                log_file.write(f"Biomni Launcher — {timestamp}\n")
                log_file.write(f"Gene: {gene}\nModel: {model}\nPrompt:\n{prompt}\n\n")
                log_file.write("=" * 60 + "\n\n")

                proc = subprocess.Popen(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
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

                proc.wait()
                status = "Completed" if proc.returncode == 0 else f"Exited with code {proc.returncode}"
                self._append_output(f"\n[{status}]\n")
                log_file.write(f"\n[{status}]\n")

        except Exception as e:
            self._append_output(f"\n[ERROR] {e}\n")

        self.after(0, self._on_workflow_done)

    def _on_workflow_done(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("Ready")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BiomniLauncher()
    app.mainloop()
