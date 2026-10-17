#!/usr/bin/env python3
"""根据 rules/skills.json 把 rules/ 下的规则文件生成成 skills/<name>/SKILL.md。

skills.json 负责记录每个规则对应的 skill 名与 description（触发条件写在里面），
规则正文则原样取自 rules/ 下的源文件，避免两处内容各写一遍。
"""

import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RULES_DIR = BASE_DIR / "rules"
SKILLS_DIR = BASE_DIR / "skills"
META_FILE = RULES_DIR / "skills.json"

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def yaml_escape(text: str) -> str:
    """把 description 折成 YAML 单行安全写法。"""
    if '"' not in text:
        return f'"{text}"'
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def split_title(content: str, fallback: str) -> tuple[str, str]:
    """取规则文件里第一个二级标题作为 skill 标题，其余内容作为正文。"""
    lines = content.splitlines()
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            title = match.group(1)
            body = "\n".join(lines[index + 1 :]).strip()
            return title, body
    return fallback, content.strip()


def build_skill_md(name: str, description: str, title: str, body: str, source: str) -> str:
    parts = [
        "---",
        f"name: {name}",
        f"description: {yaml_escape(description)}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if body:
        parts.extend([body, ""])
    parts.extend([f"> 来源：`rules/{source}`，由 `rules2skills.py` 生成，请勿手动编辑。", ""])
    return "\n".join(parts)


def main() -> int:
    if not RULES_DIR.is_dir():
        print(f"未找到 rules 目录: {RULES_DIR}")
        return 1
    if not META_FILE.is_file():
        print(f"未找到规则描述文件: {META_FILE}")
        return 1

    try:
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{META_FILE} 不是合法 JSON: {exc}")
        return 1

    entries = meta.get("skills") if isinstance(meta, dict) else meta
    if not isinstance(entries, list) or not entries:
        print(f"{META_FILE} 中缺少非空的 skills 数组")
        return 1

    seen_names: set[str] = set()
    errors: list[str] = []
    targets: list[tuple[Path, str]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"非法的规则条目: {entry!r}")
            continue
        source = entry.get("source")
        name = entry.get("name")
        description = entry.get("description")

        missing = [
            key
            for key, value in (
                ("source", source),
                ("name", name),
                ("description", description),
            )
            if not (isinstance(value, str) and value.strip())
        ]
        if missing:
            errors.append(f"条目缺少必填字段 {missing}: {entry!r}")
            continue
        if name in seen_names:
            errors.append(f"skill 名重复: {name}")
            continue

        source_path = RULES_DIR / source
        if not source_path.is_file():
            errors.append(f"找不到规则源文件: rules/{source}")
            continue

        seen_names.add(name)
        title, body = split_title(source_path.read_text(encoding="utf-8").strip(), name)
        content = build_skill_md(name, description.strip(), title, body, source)
        targets.append((SKILLS_DIR / name / "SKILL.md", content))

    if errors:
        print("生成失败，请先修正以下问题：")
        for error in errors:
            print(f"  - {error}")
        return 1

    for target, content in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"已生成: {target.relative_to(BASE_DIR)}")

    print(f"\n规则转 skill 完成，共 {len(targets)} 个 -> {SKILLS_DIR.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
