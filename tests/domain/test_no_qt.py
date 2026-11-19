import ast
import pathlib

DOMAIN = pathlib.Path(__file__).resolve().parents[2] / "src" / "mnemo" / "domain"


def test_domain_does_not_import_qt_or_sqlite():
    banned = {"PyQt6", "sqlite3"}
    for path in DOMAIN.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"
