#!/usr/bin/env python3
"""
章节合并脚本
将指定小说项目的所有章节按序号合并为单一文件。

用法：
    # 自动从项目根目录发现小说目录
    python 脚本/合并章节.py

    # 指定小说目录
    python 脚本/合并章节.py "万古神龙：我的血脉全靠吞"
"""

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def natural_sort_key(name: str) -> list:
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def find_novel_dirs() -> list[Path]:
    """自动发现项目根目录下的小说项目文件夹"""
    novel_dirs = []
    for d in PROJECT_ROOT.iterdir():
        if d.is_dir() and d.name not in (".git", "自动化", "脚本", "校对", "配置", "__pycache__"):
            # 有 执行/章节/ 子目录 = 小说项目
            if (d / "执行" / "章节").exists():
                novel_dirs.append(d)
    return novel_dirs


def merge_chapters(novel_dir: Path):
    chapters_dir = novel_dir / "执行" / "章节"
    output_dir = novel_dir / "输出"
    output_file = output_dir / "合并全文.md"

    chapters = sorted(
        [f for f in chapters_dir.iterdir() if f.suffix == ".md"],
        key=lambda f: natural_sort_key(f.stem),
    )

    if not chapters:
        print(f"未找到章节文件: {chapters_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as out:
        out.write("# 合并全文\n\n")
        for ch in chapters:
            text = ch.read_text(encoding="utf-8")
            out.write(text)
            out.write("\n\n---\n\n")

    print(f"已合并 {len(chapters)} 个章节 → {output_file}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        novel_dir = PROJECT_ROOT / sys.argv[1]
        if novel_dir.exists():
            merge_chapters(novel_dir)
        else:
            print(f"目录不存在: {novel_dir}")
    else:
        dirs = find_novel_dirs()
        if not dirs:
            print("未找到小说项目目录。请指定：python 脚本/合并章节.py \"小说名\"")
        else:
            for d in dirs:
                print(f"合并: {d.name}")
                merge_chapters(d)
