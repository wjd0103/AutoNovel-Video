#!/usr/bin/env python3
"""
文本格式化脚本
对指定章节执行标准格式化操作：
- 全角标点统一
- 多余空行清理
- 中英文之间添加空格（可选）
"""

import re
import sys
from pathlib import Path


def format_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = text.replace("...", "……")
    text = text.replace(",", "，")
    text = text.replace(";", "；")
    text = text.replace("(", "（")
    text = text.replace(")", "）")
    return text.strip()


def main():
    if len(sys.argv) < 2:
        print("用法: python 格式化文本.py <文件路径>")
        print("示例: python 脚本/格式化文本.py \"万古神龙：我的血脉全靠吞/执行/章节/第001章.md\"")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"文件不存在: {file_path}")
        sys.exit(1)

    original = file_path.read_text(encoding="utf-8")
    formatted = format_text(original)
    file_path.write_text(formatted, encoding="utf-8")

    print(f"格式化完成: {file_path}")


if __name__ == "__main__":
    main()
