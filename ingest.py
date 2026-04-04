"""Ferramenta de ingestao de documentos com interface grafica.

Converte documentos (PDF, DOCX, TXT) para Markdown e indexa no banco de dados.

Uso:
    python ingest.py                  # Abre janela para selecionar pasta
    python ingest.py "C:/minha/pasta" # Usa pasta especificada
"""

from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

# Configuracoes
DB_PATH = Path(__file__).parent / "db" / "sped.db"
MARKDOWN_DIR = Path(__file__).parent / "data" / "markdown" / "legislacao"
CATEGORY = "legislacao"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def find_files(directory: Path) -> list[Path]:
    """Encontra arquivos suportados no diretorio."""
    files: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(directory.glob(f"*{ext}"))
        files.extend(directory.glob(f"*{ext.upper()}"))
    # Adicionar .doc tambem
    files.extend(directory.glob("*.doc"))
    files.extend(directory.glob("*.DOC"))
    return sorted(set(files))


def run_ingestion(
    input_dir: Path,
    on_progress: callable,
    on_file_status: callable,
    on_done: callable,
    on_error: callable,
) -> None:
    """Executa o pipeline de ingestao: converter + indexar.

    Callbacks:
        on_progress(current, total, percent)
        on_file_status(filename, status, detail)  # status: 'converting', 'indexing', 'ok', 'error', 'skipped'
        on_done(stats)
        on_error(message)
    """
    try:
        # Importar aqui para nao bloquear a UI
        sys.path.insert(0, str(Path(__file__).parent))
        from src.converter import convert_file_to_markdown
        from src.indexer import init_db

        files = find_files(input_dir)
        total = len(files)

        if total == 0:
            on_error(f"Nenhum arquivo suportado encontrado em:\n{input_dir}\n\nExtensoes aceitas: PDF, DOCX, TXT")
            return

        MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

        stats = {
            "total": total,
            "converted": 0,
            "skipped": 0,
            "indexed": 0,
            "errors": 0,
            "error_files": [],
        }

        # Fase 1: Converter para Markdown
        on_file_status("", "stage", "Fase 1/2: Convertendo documentos para Markdown...")

        for i, file_path in enumerate(files):
            filename = file_path.name
            md_path = MARKDOWN_DIR / f"{file_path.stem}.md"

            on_progress(i, total, int(i / total * 50))

            # Skip se ja existe
            if md_path.exists():
                on_file_status(filename, "skipped", "Ja convertido")
                stats["skipped"] += 1
                continue

            on_file_status(filename, "converting", "Convertendo...")

            try:
                markdown = convert_file_to_markdown(file_path)
                if markdown.strip():
                    md_path.write_text(markdown, encoding="utf-8")
                    on_file_status(filename, "ok", f"Convertido ({len(markdown):,} chars)")
                    stats["converted"] += 1
                else:
                    on_file_status(filename, "error", "Arquivo vazio apos conversao")
                    stats["errors"] += 1
                    stats["error_files"].append(filename)
            except Exception as e:
                on_file_status(filename, "error", str(e)[:100])
                stats["errors"] += 1
                stats["error_files"].append(filename)

        # Fase 2: Indexar no banco
        on_file_status("", "stage", "Fase 2/2: Indexando no banco de dados...")
        on_progress(total, total, 60)

        try:
            conn = init_db(DB_PATH)
            md_files = sorted(MARKDOWN_DIR.glob("*.md"))
            total_md = len(md_files)

            for j, md_path in enumerate(md_files):
                # Verificar se ja indexado
                row = conn.execute(
                    "SELECT 1 FROM indexed_files WHERE source_file = ? AND category = ?",
                    (md_path.name, CATEGORY),
                ).fetchone()
                if row:
                    on_progress(j, total_md, 60 + int(j / max(total_md, 1) * 35))
                    continue

                on_file_status(md_path.name, "indexing", "Indexando...")
                on_progress(j, total_md, 60 + int(j / max(total_md, 1) * 35))

                try:
                    content = md_path.read_text(encoding="utf-8")

                    from src.indexer import (
                        _chunk_markdown,
                        _extract_register_fields,
                        _insert_chunks,
                        _insert_register_fields,
                    )

                    chunks = _chunk_markdown(content, md_path.name, CATEGORY)
                    fields = _extract_register_fields(content)

                    if chunks:
                        inserted = _insert_chunks(conn, chunks, CATEGORY)
                        stats["indexed"] += inserted

                    if fields:
                        _insert_register_fields(conn, fields)

                    conn.execute(
                        "INSERT OR REPLACE INTO indexed_files (source_file, category) VALUES (?, ?)",
                        (md_path.name, CATEGORY),
                    )
                    conn.commit()
                    on_file_status(md_path.name, "ok", f"Indexado ({len(chunks)} chunks)")

                except Exception as e:
                    on_file_status(md_path.name, "error", f"Erro ao indexar: {e!s:.80}")
                    stats["errors"] += 1

            conn.close()

        except Exception as e:
            on_error(f"Erro ao indexar no banco:\n{e}")
            return

        on_progress(total, total, 100)
        on_done(stats)

    except Exception:
        on_error(f"Erro inesperado:\n{traceback.format_exc()}")


# ──────────────────────────────────────────────
# Interface Grafica (tkinter)
# ──────────────────────────────────────────────

def run_gui(initial_dir: str | None = None) -> None:
    """Abre a interface grafica de ingestao."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("SPED - Ingestao de Documentos")
    root.geometry("750x550")
    root.resizable(True, True)

    # Variaveis
    folder_var = tk.StringVar(value=initial_dir or "")
    progress_var = tk.DoubleVar(value=0)
    status_var = tk.StringVar(value="Selecione uma pasta para iniciar.")
    running = False

    # ── Layout ──

    # Header
    header = tk.Frame(root, pady=10, padx=15)
    header.pack(fill=tk.X)
    tk.Label(header, text="Ingestao de Documentos", font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)
    tk.Label(header, text="Converte PDF/DOCX/TXT para Markdown e indexa no banco de dados",
             font=("Segoe UI", 9), fg="gray").pack(anchor=tk.W)

    # Pasta
    folder_frame = tk.Frame(root, padx=15, pady=5)
    folder_frame.pack(fill=tk.X)
    tk.Label(folder_frame, text="Pasta:", font=("Segoe UI", 9)).pack(side=tk.LEFT)
    folder_entry = tk.Entry(folder_frame, textvariable=folder_var, font=("Segoe UI", 9), width=60)
    folder_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

    def browse():
        path = filedialog.askdirectory(title="Selecione a pasta com os documentos")
        if path:
            folder_var.set(path)
            files = find_files(Path(path))
            status_var.set(f"{len(files)} arquivo(s) encontrado(s) na pasta.")

    tk.Button(folder_frame, text="Procurar...", command=browse, font=("Segoe UI", 9)).pack(side=tk.LEFT)

    # Progresso
    progress_frame = tk.Frame(root, padx=15, pady=10)
    progress_frame.pack(fill=tk.X)
    progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100, length=700)
    progress_bar.pack(fill=tk.X)
    status_label = tk.Label(progress_frame, textvariable=status_var, font=("Segoe UI", 9), fg="gray", anchor=tk.W)
    status_label.pack(fill=tk.X, pady=(3, 0))

    # Log
    log_frame = tk.Frame(root, padx=15, pady=5)
    log_frame.pack(fill=tk.BOTH, expand=True)
    tk.Label(log_frame, text="Log:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)

    log_text = tk.Text(log_frame, height=15, font=("Consolas", 9), state=tk.DISABLED, bg="#1e1e1e", fg="#cccccc")
    log_scrollbar = tk.Scrollbar(log_frame, command=log_text.yview)
    log_text.config(yscrollcommand=log_scrollbar.set)
    log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    log_text.pack(fill=tk.BOTH, expand=True)

    # Tags de cor
    log_text.tag_config("ok", foreground="#4ec9b0")
    log_text.tag_config("error", foreground="#f44747")
    log_text.tag_config("skip", foreground="#808080")
    log_text.tag_config("info", foreground="#569cd6")
    log_text.tag_config("stage", foreground="#dcdcaa", font=("Consolas", 9, "bold"))

    def log(msg: str, tag: str = "info") -> None:
        log_text.config(state=tk.NORMAL)
        log_text.insert(tk.END, msg + "\n", tag)
        log_text.see(tk.END)
        log_text.config(state=tk.DISABLED)

    # Botoes
    btn_frame = tk.Frame(root, padx=15, pady=10)
    btn_frame.pack(fill=tk.X)

    def start_ingestion():
        nonlocal running
        folder = folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Aviso", "Selecione uma pasta primeiro.")
            return
        input_dir = Path(folder)
        if not input_dir.exists():
            messagebox.showerror("Erro", f"Pasta nao encontrada:\n{folder}")
            return

        files = find_files(input_dir)
        if not files:
            messagebox.showwarning("Aviso", "Nenhum arquivo suportado na pasta.\nExtensoes: PDF, DOCX, TXT")
            return

        running = True
        start_btn.config(state=tk.DISABLED)
        log_text.config(state=tk.NORMAL)
        log_text.delete("1.0", tk.END)
        log_text.config(state=tk.DISABLED)

        log(f"Iniciando ingestao de {len(files)} arquivo(s)...", "stage")
        log(f"Pasta: {folder}", "info")
        log(f"Banco: {DB_PATH}", "info")
        log(f"Markdown: {MARKDOWN_DIR}", "info")
        log("", "info")

        def on_progress(current, total, percent):
            root.after(0, lambda: progress_var.set(percent))

        def on_file_status(filename, status, detail):
            def _stage():
                status_var.set(detail)
                log(f"\n{'='*50}", "stage")
                log(detail, "stage")
                log("=" * 50, "stage")

            def _ok():
                status_var.set(f"OK: {filename}")
                log(f"  [OK] {filename} - {detail}", "ok")

            def _err():
                status_var.set(f"ERRO: {filename}")
                log(f"  [ERRO] {filename} - {detail}", "error")

            if status == "stage":
                root.after(0, _stage)
            elif status == "ok":
                root.after(0, _ok)
            elif status == "error":
                root.after(0, _err)
            elif status == "skipped":
                root.after(0, lambda: log(f"  [SKIP] {filename} - {detail}", "skip"))
            elif status == "converting":
                root.after(0, lambda: status_var.set(f"Convertendo: {filename}"))
            elif status == "indexing":
                root.after(0, lambda: status_var.set(f"Indexando: {filename}"))

        def on_done(stats):
            nonlocal running
            running = False

            def _update():
                progress_var.set(100)
                log("", "info")
                log(f"{'='*50}", "stage")
                log("  INGESTAO FINALIZADA", "stage")
                log(f"{'='*50}", "stage")
                log(f"  Arquivos encontrados: {stats['total']}", "info")
                log(f"  Convertidos:          {stats['converted']}", "ok")
                log(f"  Ja existentes (skip): {stats['skipped']}", "skip")
                log(f"  Chunks indexados:     {stats['indexed']}", "ok")
                log(f"  Erros:                {stats['errors']}", "error" if stats["errors"] > 0 else "ok")
                if stats["error_files"]:
                    log("  Arquivos com erro:", "error")
                    for f in stats["error_files"]:
                        log(f"    - {f}", "error")
                msg = (f"Finalizado! {stats['converted']} convertidos, "
                       f"{stats['indexed']} chunks, {stats['errors']} erros.")
                status_var.set(msg)
                start_btn.config(state=tk.NORMAL)
                messagebox.showinfo("Concluido", f"Ingestao finalizada!\n\n"
                                    f"Convertidos: {stats['converted']}\n"
                                    f"Chunks indexados: {stats['indexed']}\n"
                                    f"Erros: {stats['errors']}")

            root.after(0, _update)

        def on_error_cb(message):
            nonlocal running
            running = False
            root.after(0, lambda: [
                log(f"\n[ERRO FATAL] {message}", "error"),
                status_var.set("Erro durante ingestao."),
                start_btn.config(state=tk.NORMAL),
                messagebox.showerror("Erro", message),
            ])

        # Rodar em thread separada para nao travar a UI
        thread = threading.Thread(
            target=run_ingestion,
            args=(input_dir, on_progress, on_file_status, on_done, on_error_cb),
            daemon=True,
        )
        thread.start()

    start_btn = tk.Button(btn_frame, text="Iniciar Ingestao", command=start_ingestion,
                          font=("Segoe UI", 10, "bold"), bg="#007acc", fg="white",
                          padx=20, pady=5, cursor="hand2")
    start_btn.pack(side=tk.RIGHT)

    tk.Button(btn_frame, text="Fechar", command=root.destroy,
              font=("Segoe UI", 9), padx=10).pack(side=tk.RIGHT, padx=5)

    # Se ja tem pasta, pre-carregar contagem
    if initial_dir:
        files = find_files(Path(initial_dir))
        status_var.set(f"{len(files)} arquivo(s) encontrado(s) na pasta.")

    root.mainloop()


# ──────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────

if __name__ == "__main__":
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    run_gui(initial)
