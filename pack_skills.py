import os
import zipfile
from pathlib import Path

def should_ignore(rel_path: Path) -> bool:
    for part in rel_path.parts:
        if part.startswith(".") or part == "__pycache__":
            return True
    if rel_path.suffix == ".pyc":
        return True
    return False

def main():
    base_dir = Path(__file__).resolve().parent
    skills_dir = base_dir / "skills"
    output_dir = base_dir / "skills-pack"

    if not skills_dir.exists() or not skills_dir.is_dir():
        print(f"未找到 skills 目录: {skills_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    for item in sorted(skills_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue

        zip_path = output_dir / f"{item.name}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in item.rglob("*"):
                rel_to_item = file_path.relative_to(item)
                if should_ignore(rel_to_item):
                    continue
                arcname = file_path.relative_to(skills_dir)
                zf.write(file_path, arcname=arcname)

        print(f"已打包: {item.name} -> {zip_path.relative_to(base_dir)}")

    print(f"\n所有技能打包完成，输出目录: {output_dir.relative_to(base_dir)}")

if __name__ == "__main__":
    main()
