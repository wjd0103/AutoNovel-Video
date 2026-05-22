#!/usr/bin/env python3
"""
小说章节质量检查工具
=========================
检查内容：字数统计、完整性校验、异常字符检测。
可在发布前作为前置检查步骤运行。

用法：
    # 检查指定项目的所有章节
    python 自动化/质检/质检.py --project 万古神龙

    # 检查指定章节范围
    python 自动化/质检/质检.py --project 万古神龙 --start 56 --end 66

    # 检查并自动报告不合格章节
    python 自动化/质检/质检.py --project 万古神龙 --min-words 2500

    # 检查所有项目
    python 自动化/质检/质检.py --all
"""

import re
import sys
import yaml
import argparse
from pathlib import Path
from typing import List, Tuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "自动化" / "配置"

# 番茄小说章节字数标准（2026年5月更新：最低3000字）
DEFAULT_MIN_WORDS = 3000    # 最低汉字数（硬性标准）
DEFAULT_MAX_WORDS = 6000    # 最高汉字数
DEFAULT_IDEAL_MIN = 3000    # 理想最低（与硬性标准一致）
DEFAULT_IDEAL_MAX = 4500    # 理想最高


def load_project_config(project_name: str) -> dict:
    """加载项目配置"""
    # 精确匹配：发布配置-{项目名}.yaml
    for f in sorted(CONFIG_DIR.glob("*.yaml"), reverse=True):
        if f.stem == f"发布配置-{project_name}":
            with open(f, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)
    # 如果没找到，尝试通过文件名关键词匹配
    for f in CONFIG_DIR.glob("*.yaml"):
        if project_name in f.stem:
            with open(f, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)
    return {}


def get_chapters_dir(config: dict, project_name: str = "") -> Optional[Path]:
    """获取章节目录"""
    novel_dir = config.get("作品", {}).get("小说目录", "")
    if novel_dir:
        path = Path(novel_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        chapters = path / "执行" / "章节"
        if chapters.exists():
            return chapters
    # 按书名找
    book_name = config.get("作品", {}).get("书名", "")
    if book_name:
        path = PROJECT_ROOT / book_name / "执行" / "章节"
        if path.exists():
            return path
    # 按项目名找
    if project_name:
        path = PROJECT_ROOT / project_name / "执行" / "章节"
        if path.exists():
            return path
    return None


def discover_chapters(chapters_dir: Path) -> List[Tuple[int, str, Path]]:
    """发现所有章节文件"""
    chapters = []
    for f in sorted(chapters_dir.glob("第*.md")):
        match = re.match(r"^第(\d+)章[·\.,，、\s]*(.+)\.md$", f.name)
        if match:
            chapters.append((int(match.group(1)), match.group(2), f))
    return chapters


def count_chinese_chars(text: str) -> int:
    """统计中文字符数（仅汉字）"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def check_abnormal_chars(text: str) -> List[str]:
    """检测异常字符（HTML标签、写作指令残留等）"""
    issues = []
    # HTML标签
    html_tags = re.findall(r'<[^>]+>', text)
    for tag in html_tags:
        issues.append(f"发现HTML标签: {tag[:50]}")
    # 写作指令残留
    instructions = re.findall(r'（.*?我[将要将在].*?）', text)
    for inst in instructions:
        issues.append(f"发现写作指令残留: {inst[:50]}")
    # 多余的尖括号
    if '">' in text or '"<' in text:
        issues.append("发现异常尖括号")
    return issues


def check_quality(
    chapters_dir: Path,
    start: int = 1,
    end: int = 9999,
    min_words: int = DEFAULT_MIN_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
    verbose: bool = True
) -> Tuple[bool, list]:
    """
    执行质量检查
    返回: (是否全部通过, 检查结果列表)
    """
    chapters = discover_chapters(chapters_dir)
    chapters = [(n, t, p) for n, t, p in chapters if start <= n <= end]

    if not chapters:
        print(f"  [警告] 在 {chapters_dir} 中未找到章节文件（范围: {start}-{end}）")
        return False, []

    results = []
    all_pass = True

    # 表头
    if verbose:
        print(f"{'='*80}")
        print(f"  章节质量检查报告")
        print(f"  目录: {chapters_dir}")
        print(f"  范围: 第{start}章 ~ 第{end}章")
        print(f"  字数标准: {min_words}~{max_words}汉字（理想: {DEFAULT_IDEAL_MIN}~{DEFAULT_IDEAL_MAX}）")
        print(f"{'='*80}")
        print(f"{'章节':<16} {'汉字数':<10} {'行数':<8} {'状态':<12} {'备注'}")
        print(f"{'-'*80}")

    for num, title, path in chapters:
        text = path.read_text(encoding="utf-8")
        chinese_chars = count_chinese_chars(text)
        lines = text.count('\n')

        issues = []
        status = "✅"

        # 字数检查
        if chinese_chars < min_words:
            issues.append(f"字数不足（{chinese_chars} < {min_words}）")
            status = "❌"
            all_pass = False
        elif chinese_chars < DEFAULT_IDEAL_MIN:
            issues.append(f"字数偏低（{chinese_chars} < 推荐{DEFAULT_IDEAL_MIN}）")
            status = "⚠️"
        elif chinese_chars > max_words:
            issues.append(f"字数过多（{chinese_chars} > {max_words}）")
            status = "⚠️"

        # 异常字符检查
        abnormal = check_abnormal_chars(text)
        if abnormal:
            issues.extend(abnormal)
            if status == "✅":
                status = "❌"
            all_pass = False

        # 首尾完整性检查
        if not text.strip().endswith(("。", "」", "”", "！", "？", "）", ")")):
            issues.append("结尾可能不完整（未见句尾标点）")

        # 输出
        remark = "；".join(issues) if issues else ""
        if verbose:
            print(f"  第{num:02d}章 {title:<12} {chinese_chars:<8} {lines:<6} {status:<10} {remark}")

        results.append({
            "num": num,
            "title": title,
            "path": path,
            "chars": chinese_chars,
            "lines": lines,
            "status": status,
            "issues": issues,
        })

    # 汇总
    if verbose:
        print(f"{'-'*80}")
        passed = sum(1 for r in results if r["status"] == "✅")
        warned = sum(1 for r in results if r["status"] == "⚠️")
        failed = sum(1 for r in results if r["status"] == "❌")
        print(f"  总计: {len(results)}章 | ✅ {passed}通过 | ⚠️ {warned}警告 | ❌ {failed}未通过")
        print(f"{'='*80}\n")

    return all_pass, results


def main():
    parser = argparse.ArgumentParser(description="小说章节质量检查工具")
    parser.add_argument("--project", type=str, default="", help="项目名称")
    parser.add_argument("--start", type=int, default=1, help="起始章节")
    parser.add_argument("--end", type=int, default=9999, help="结束章节")
    parser.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS, help="最低汉字数")
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS, help="最高汉字数")
    parser.add_argument("--all", action="store_true", help="检查所有项目")
    parser.add_argument("--quiet", action="store_true", help="静默模式，只输出结果")
    args = parser.parse_args()

    if args.all:
        # 检查所有项目
        configs = sorted(CONFIG_DIR.glob("发布配置-*.yaml"))
        if not configs:
            configs = sorted(CONFIG_DIR.glob("*.yaml"))
        overall_pass = True
        for config_file in configs:
            project_name = config_file.stem.replace("发布配置-", "")
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            ch_dir = get_chapters_dir(config, project_name)
            if not ch_dir:
                print(f"[跳过] {project_name}: 章节目录不存在")
                continue
            print(f"\n[{project_name}]")
            passed, _ = check_quality(ch_dir, args.start, args.end, args.min_words, args.max_words, verbose=True)
            if not passed:
                overall_pass = False
        if not overall_pass:
            sys.exit(1)
        return

    if not args.project:
        print("请指定项目名称（--project）或使用 --all 检查所有项目")
        sys.exit(1)

    config = load_project_config(args.project)
    ch_dir = get_chapters_dir(config, args.project)
    if not ch_dir:
        print(f"[错误] 找不到项目 '{args.project}' 的章节目录")
        sys.exit(1)

    passed, results = check_quality(
        ch_dir,
        start=args.start,
        end=args.end,
        min_words=args.min_words,
        max_words=args.max_words,
        verbose=not args.quiet,
    )

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
