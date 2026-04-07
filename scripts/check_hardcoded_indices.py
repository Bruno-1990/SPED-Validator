#!/usr/bin/env python3
"""Lint customizado: detecta acesso por índice numérico em listas 'fields'.

Uso: python scripts/check_hardcoded_indices.py src/validators/

Retorna exit code 1 se encontrar violações.
Adicione ao CI e ao pre-commit para enforcement automático.
"""

import ast
import sys
from pathlib import Path


# Número mínimo de índice para considerar suspeito.
# 0 = REG (sempre seguro), 1 pode ser campos simples como IND_MOV
MIN_SUSPICIOUS_INDEX = 2

# Nomes de variáveis considerados 'fields' (lista de campos SPED)
FIELD_VARIABLE_NAMES = {"fields", "record_fields", "sped_fields"}

# Arquivos/diretórios a ignorar
IGNORED_PATHS = {
    "field_registry.py",
    "helpers_registry.py",
    "tolerance.py",
    "__init__.py",
    "conftest.py",
}


class HardcodedIndexVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.violations: list[tuple[int, str]] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in FIELD_VARIABLE_NAMES
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
            and node.slice.value >= MIN_SUSPICIOUS_INDEX
        ):
            self.violations.append((
                node.lineno,
                f"Índice hardcoded: {node.value.id}[{node.slice.value}] — "
                f"use fval(fields, REGISTER, FIELD_NAME) em vez disso.",
            ))
        self.generic_visit(node)


def check_file(path: Path) -> list[tuple[str, int, str]]:
    if path.name in IGNORED_PATHS:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    visitor = HardcodedIndexVisitor(str(path))
    visitor.visit(tree)
    return [(str(path), line, msg) for line, msg in visitor.violations]


def main(targets: list[str]) -> int:
    all_violations = []
    for target in targets:
        p = Path(target)
        if p.is_file():
            all_violations.extend(check_file(p))
        elif p.is_dir():
            for py_file in sorted(p.rglob("*.py")):
                all_violations.extend(check_file(py_file))

    if all_violations:
        print(f"{len(all_violations)} índice(s) hardcoded encontrado(s):\n")
        for path, line, msg in all_violations:
            print(f"  {path}:{line}: {msg}")
        print()
        print("Corrija usando fval(fields, REGISTER, FIELD_NAME) de helpers_registry.py")
        return 1
    else:
        print("Nenhum índice hardcoded encontrado nos validadores.")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["src/validators/"]))
