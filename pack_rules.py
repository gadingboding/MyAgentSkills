#!/usr/bin/env python3
"""将 rules/ 目录下的所有规则文件合并打包为 context/AGENTS.md。"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RULES_DIR = BASE_DIR / "rules"
OUTPUT_DIR = BASE_DIR / "context"
OUTPUT_FILE = OUTPUT_DIR / "AGENTS.md"

DOC_TITLE = "agent工作和响应规范"


def collect_rule_files(rules_dir: Path) -> list[Path]:
    """递归收集规则文件，按相对路径排序，忽略隐藏文件与 __pycache__。"""
    files = []
    for path in rules_dir.rglob("*.md"):
        rel_parts = path.relative_to(rules_dir).parts
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p.relative_to(rules_dir)))


def build_document(files: list[Path], rules_dir: Path) -> str:
    sections = []

    for path in files:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        sections.append(content)

    parts = [f"# {DOC_TITLE}", ""]
    for section in sections:
        parts.extend([section, ""])
    return "\n".join(parts)


def main() -> None:
    if not RULES_DIR.is_dir():
        print(f"未找到 rules 目录: {RULES_DIR}")
        return

    files = collect_rule_files(RULES_DIR)
    if not files:
        print(f"rules 目录中没有可打包的 markdown 文件: {RULES_DIR}")
        return

    document = build_document(files, RULES_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(document, encoding="utf-8")

    for path in files:
        print(f"已合并: {path.relative_to(BASE_DIR)}")
    print(
        f"\n规则打包完成，共 {len(files)} 个文件 -> "
        f"{OUTPUT_FILE.relative_to(BASE_DIR)}"
    )


if __name__ == "__main__":
    main()
