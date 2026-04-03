"""CLI principal do sistema SPED EFD."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config


def cmd_convert(args: argparse.Namespace) -> None:
    """Converte documentos (PDF, DOCX, TXT) para Markdown."""
    from src.converter import convert_all_docs

    force = not args.force is False if hasattr(args, "force") else False

    # Converter Guia Pratico
    print("=" * 50)
    print("[1/2] Convertendo GUIA PRATICO")
    print("=" * 50)
    if config.GUIA_DIR.exists():
        created_guia = convert_all_docs(
            config.GUIA_DIR, config.MARKDOWN_GUIA_DIR,
            skip_existing=not args.force,
        )
        print(f"  {len(created_guia)} arquivo(s) criado(s) em {config.MARKDOWN_GUIA_DIR}")
    else:
        print(f"  Pasta nao encontrada: {config.GUIA_DIR}")

    # Converter Legislacao
    print()
    print("=" * 50)
    print("[2/2] Convertendo LEGISLACAO")
    print("=" * 50)
    if config.LEGISLACAO_DIR.exists():
        created_leg = convert_all_docs(
            config.LEGISLACAO_DIR, config.MARKDOWN_LEGISLACAO_DIR,
            skip_existing=not args.force,
        )
        print(f"  {len(created_leg)} arquivo(s) criado(s) em {config.MARKDOWN_LEGISLACAO_DIR}")
    else:
        print(f"  Pasta nao encontrada: {config.LEGISLACAO_DIR}")

    total = len(created_guia if config.GUIA_DIR.exists() else []) + \
            len(created_leg if config.LEGISLACAO_DIR.exists() else [])
    print(f"\nTotal: {total} arquivo(s) Markdown criado(s).")


def cmd_index(args: argparse.Namespace) -> None:
    """Indexa arquivos Markdown no banco SQLite (separado por categoria)."""
    from src.indexer import index_all_markdown

    db_path = Path(args.db) if args.db else config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    force = args.force

    total_chunks = 0

    # Indexar Guia Pratico
    print("=" * 50)
    print("[1/2] Indexando GUIA PRATICO")
    print("=" * 50)
    if config.MARKDOWN_GUIA_DIR.exists():
        md_count = len(list(config.MARKDOWN_GUIA_DIR.glob("*.md")))
        if md_count > 0:
            chunks = index_all_markdown(
                config.MARKDOWN_GUIA_DIR, db_path,
                category="guia", skip_existing=not force,
            )
            total_chunks += chunks
            print(f"  {chunks} chunks do guia indexados.")
        else:
            print("  Nenhum .md encontrado.")
    else:
        print(f"  Pasta nao encontrada: {config.MARKDOWN_GUIA_DIR}")
        print("  Execute 'python cli.py convert' primeiro.")

    # Indexar Legislacao
    print()
    print("=" * 50)
    print("[2/2] Indexando LEGISLACAO")
    print("=" * 50)
    if config.MARKDOWN_LEGISLACAO_DIR.exists():
        md_count = len(list(config.MARKDOWN_LEGISLACAO_DIR.glob("*.md")))
        if md_count > 0:
            chunks = index_all_markdown(
                config.MARKDOWN_LEGISLACAO_DIR, db_path,
                category="legislacao", skip_existing=not force,
            )
            total_chunks += chunks
            print(f"  {chunks} chunks da legislacao indexados.")
        else:
            print("  Nenhum .md encontrado.")
    else:
        print(f"  Pasta nao encontrada: {config.MARKDOWN_LEGISLACAO_DIR}")
        print("  Execute 'python cli.py convert' primeiro.")

    print(f"\nTotal: {total_chunks} chunks indexados no banco.")


def cmd_validate(args: argparse.Namespace) -> None:
    """Valida um arquivo SPED EFD."""
    from src.parser import parse_sped_file
    from src.validator import load_field_definitions, validate_records, generate_report
    from src.searcher import search_for_error

    sped_path = Path(args.file)
    db_path = Path(args.db) if args.db else config.DB_PATH

    if not sped_path.exists():
        print(f"Arquivo SPED nao encontrado: {sped_path}")
        sys.exit(1)

    if not db_path.exists():
        print(f"Banco de dados nao encontrado: {db_path}")
        print("Execute 'python cli.py convert' e 'python cli.py index' primeiro.")
        sys.exit(1)

    # Parsear arquivo SPED
    print(f"Parseando {sped_path.name}...")
    records = parse_sped_file(sped_path)
    print(f"  {len(records)} registros encontrados.")

    # Carregar definicoes e validar
    print("Validando...")
    field_defs = load_field_definitions(db_path)
    errors = validate_records(records, field_defs)

    if not errors:
        print("\nNenhum erro encontrado!")
        return

    print(f"\n{len(errors)} erro(s) encontrado(s).")

    # Buscar documentacao para cada erro
    docs: dict[int, list[str]] = {}
    if not args.no_search:
        print("Buscando documentacao para os erros...")
        for i, err in enumerate(errors):
            try:
                results = search_for_error(
                    register=err.register,
                    field_name=err.field_name,
                    field_no=err.field_no,
                    error_message=err.message,
                    db_path=db_path,
                    top_k=2,
                )
                if results:
                    docs[i] = [r.chunk.content for r in results]
            except Exception:
                pass

    # Gerar relatorio
    report = generate_report(errors, docs if docs else None)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = sped_path.with_name(f"{sped_path.stem}_relatorio.md")

    output_path.write_text(report, encoding="utf-8")
    print(f"Relatorio salvo em: {output_path}")

    # Mostrar resumo no terminal
    print("\n--- Resumo ---")
    by_type: dict[str, int] = {}
    for e in errors:
        by_type[e.error_type] = by_type.get(e.error_type, 0) + 1
    for etype, count in sorted(by_type.items()):
        print(f"  {etype}: {count}")


def cmd_search(args: argparse.Namespace) -> None:
    """Busca na documentacao indexada."""
    from src.searcher import search

    db_path = Path(args.db) if args.db else config.DB_PATH

    if not db_path.exists():
        print(f"Banco de dados nao encontrado: {db_path}")
        print("Execute 'python cli.py convert' e 'python cli.py index' primeiro.")
        sys.exit(1)

    query = " ".join(args.query)
    print(f'Buscando: "{query}"')
    if args.register:
        print(f"  Filtro registro: {args.register}")
    if args.category:
        print(f"  Filtro categoria: {args.category}")

    results = search(
        query=query,
        db_path=db_path,
        register=args.register,
        field_name=args.field,
        top_k=args.top_k,
    )

    if not results:
        print("\nNenhum resultado encontrado.")
        return

    print(f"\n{len(results)} resultado(s):\n")
    for i, r in enumerate(results, 1):
        cat = getattr(r.chunk, 'category', '?')
        print(f"--- Resultado {i} (score: {r.score:.4f}, fonte: {r.source}, cat: {cat}) ---")
        print(f"Arquivo: {r.chunk.source_file}")
        if r.chunk.register:
            print(f"Registro: {r.chunk.register}")
        if r.chunk.field_name:
            print(f"Campo: {r.chunk.field_name}")
        print(f"Secao: {r.chunk.heading}")
        print(f"\n{r.chunk.content}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sistema SPED EFD - Conversor, Validador e Busca na Documentacao",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python cli.py convert                          # Converter documentos para Markdown
  python cli.py index                            # Indexar Markdown no banco
  python cli.py validate arquivo_sped.txt        # Validar arquivo SPED
  python cli.py search IND_OPER C100             # Buscar na documentacao
  python cli.py search "substituicao tributaria" --category legislacao
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a executar")

    # convert
    p_convert = subparsers.add_parser("convert", help="Converter documentos para Markdown")
    p_convert.add_argument("--force", "-f", action="store_true", help="Reconverter arquivos existentes")

    # index
    p_index = subparsers.add_parser("index", help="Indexar Markdown no SQLite")
    p_index.add_argument("--db", help="Caminho do banco SQLite")
    p_index.add_argument("--force", "-f", action="store_true", help="Reindexar arquivos existentes")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validar arquivo SPED EFD")
    p_validate.add_argument("file", help="Caminho do arquivo SPED")
    p_validate.add_argument("--db", help="Caminho do banco SQLite")
    p_validate.add_argument("--output", "-o", help="Caminho do relatorio de saida")
    p_validate.add_argument("--no-search", action="store_true", help="Nao buscar documentacao")

    # search
    p_search = subparsers.add_parser("search", help="Buscar na documentacao")
    p_search.add_argument("query", nargs="+", help="Texto de busca")
    p_search.add_argument("--register", "-r", help="Filtrar por registro (ex: C100)")
    p_search.add_argument("--field", help="Filtrar por campo (ex: IND_OPER)")
    p_search.add_argument("--category", "-c", choices=["guia", "legislacao"], help="Filtrar por categoria")
    p_search.add_argument("--db", help="Caminho do banco SQLite")
    p_search.add_argument("--top-k", "-k", type=int, default=5, help="Numero de resultados")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "convert": cmd_convert,
        "index": cmd_index,
        "validate": cmd_validate,
        "search": cmd_search,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
