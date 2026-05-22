#!/usr/bin/env python3
"""
上下文一致性校验脚本
=====================
在章节创建/发布前执行，检查：
  1. 关键术语一致性（对照项目配置中的词汇规则表）
  2. 人物名词一致性（主角、女主、配角名称）
  3. 零的对话格式（「」引文）
  4. 职业/等级格式一致性
  5. 首行空行检查
  6. 对话逻辑检查（说话人匹配）

用法：
    # 校验单个项目所有章节
    python 脚本/上下文校验.py --project 全球灾变：我的AI能自动升级

    # 校验特定章节
    python 脚本/上下文校验.py --project 全球灾变：我的AI能自动升级 --chapter 第031章·托管（上）.md
"""

import re
import sys
import yaml
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# 全局词汇规则（跨项目通用）
# ============================================================
GLOBAL_RULES = {
    "巡查": "巡察",  # 玄幻用词，末世文不应出现
}

# ============================================================
# 项目特定词汇规则
# ============================================================
# 格式：{禁用词: 统一用词}
PROJECT_TERM_RULES = {
    "全球灾变：我的AI能自动升级": {
        "数据观察员": "数据观测员",
        "变异者": "变异体",
        "变异人": "变异体",
        "觉醒人": "觉醒者",
        "超维智能": "超维AI",
        "超维度AI": "超维AI",
        "铁壁安全区": "铁壁避难所",
        "铁壁基地": "铁壁避难所",
        "灾变级": "灾变种",
    },
    "万古神龙：我的血脉全靠吞": {
        "巡查": "巡察",
        "顶峰": "巅峰",
    },
}

# ============================================================
# 角色名词表（用于检查人名拼写一致性）
# ============================================================
PROJECT_CHARACTERS = {
    "全球灾变：我的AI能自动升级": {
        "主角": ["苏哲"],
        "女主": ["顾清寒", "萝拉", "姬如烟"],
        "AI": ["零", "零（ZERO）", "超维AI"],
        "配角": ["刘主任", "陈锋", "石磊", "赵晨", "李阳", "王磊"],
        "组织": ["铁壁避难所", "巢网", "阿尔法前哨基地", "主巢", "荒野行者"],
    },
    "万古神龙：我的血脉全靠吞": {
        "主角": ["姜尘"],
        "女主": ["苏灵儿"],
        "配角": ["楚无名", "管云昭", "铁三娘", "韩策", "沈霜", "叶归鸿", "姬远", "石寒铁"],
        "反派": ["韦煊", "何岩", "严鹤"],
        "组织": ["天脉盟", "万象商盟"],
    },
}

# ============================================================
# 校验函数
# ============================================================

def check_leading_blank_lines(filepath: Path) -> list:
    """检查首行是否有空行"""
    issues = []
    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip() == "" and lines[0] in ("\n", "\r\n"):
        issues.append({
            "type": "首行空行",
            "line": 1,
            "detail": "文件首行为空行，应直接以正文开头",
        })
    return issues


def check_terminology(content: str, filepath: Path, project_name: str) -> list:
    """检查关键术语一致性"""
    issues = []
    rules = {}
    rules.update(GLOBAL_RULES)
    if project_name in PROJECT_TERM_RULES:
        rules.update(PROJECT_TERM_RULES[project_name])

    for wrong, correct in rules.items():
        pattern = re.compile(re.escape(wrong))
        for match in pattern.finditer(content):
            start = content.rfind("\n", 0, match.start()) + 1
            line_num = content[:match.start()].count("\n") + 1
            context_start = max(0, match.start() - 20)
            context_end = min(len(content), match.end() + 20)
            context = content[context_start:context_end].replace("\n", " ")
            issues.append({
                "type": f"术语错误: {wrong}→{correct}",
                "line": line_num,
                "detail": f"...{context}...",
            })
    return issues


def check_character_names(content: str, filepath: Path, project_name: str) -> list:
    """检查角色名称拼写一致性"""
    issues = []
    if project_name not in PROJECT_CHARACTERS:
        return issues

    for category, names in PROJECT_CHARACTERS[project_name].items():
        for name in names:
            if len(name) <= 2:
                continue
            fuzzy_pattern = re.compile(re.escape(name[:2]) + r'.{0,1}' + re.escape(name[-1:]))
            for match in fuzzy_pattern.finditer(content):
                matched_text = match.group()
                if matched_text != name and matched_text not in names:
                    start = content.rfind("\n", 0, match.start()) + 1
                    line_num = content[:match.start()].count("\n") + 1
                    context_start = max(0, match.start() - 10)
                    context_end = min(len(content), match.end() + 10)
                    context = content[context_start:context_end].replace("\n", " ")
                    issues.append({
                        "type": f"角色名疑似错误: {matched_text}→{name}",
                        "line": line_num,
                        "detail": f"发现近似名称 '{matched_text}'，应为 '{name}' (上下文: {context})",
                    })
    return issues


def check_zero_dialogue_format(content: str, filepath: Path) -> list:
    """检查零的对话是否使用「」格式"""
    issues = []
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("零说") or stripped.startswith("零道") or stripped.startswith("零回答"):
            if not stripped.startswith("«") and not stripped.startswith("「"):
                if stripped.startswith("零说得") or stripped.startswith("零说的"):
                    continue
                issues.append({
                    "type": "零的对话格式",
                    "line": i,
                    "detail": f"零的对话应使用「」包裹: {stripped[:60]}",
                })
    return issues


def check_grade_format(content: str, filepath: Path) -> list:
    """检查职业等级格式一致性（F级/S级/SSS级等）"""
    issues = []
    pattern = re.compile(r'(?<![A-Za-z])([A-Z]+)\s*级')
    for match in pattern.finditer(content):
        start = content.rfind("\n", 0, match.start()) + 1
        line_num = content[:match.start()].count("\n") + 1
        full_match = match.group(0)
        expected = f"{match.group(1)}级"
        if full_match != expected:
            issues.append({
                "type": "等级格式",
                "line": line_num,
                "detail": f"等级格式不规范: '{full_match}' → '{expected}'",
            })
    return issues


def check_dialogue_continuity(content: str, filepath: Path) -> list:
    """暂不启用——中文小说对话模式复杂，待优化"""
    # 中文小说中「」常嵌入叙述段落中,"xxx。"他说。"xxx"也是常规写法
    # 暂时跳过此检查以避免大量误报
    return []


def check_special_chars(content: str, filepath: Path) -> list:
    """检查非法字符（如不应出现的#号等）"""
    issues = []
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        if "#" in line and not line.strip().startswith("#"):
            pattern = re.compile(r'#\d+')
            for match in pattern.finditer(line):
                issues.append({
                    "type": "非法字符#",
                    "line": i,
                    "detail": f"发现不应出现的'#': {match.group()}",
                })
    return issues


def check_chapter_file_integrity(filepath: Path, project_name: str) -> list:
    """检查章节文件完整性"""
    issues = []
    content = filepath.read_text(encoding="utf-8")

    if not content or len(content.strip()) < 100:
        issues.append({
            "type": "文件完整性",
            "line": 1,
            "detail": f"章节内容过短 ({len(content)}字符)",
        })

    word_count = len(content.replace("\n", "").replace(" ", ""))
    if word_count < 500:
        issues.append({
            "type": "章节字数",
            "line": 1,
            "detail": f"章节字数偏少 ({word_count}字)",
        })

    return issues


# ============================================================
# 主流程
# ============================================================

def validate_chapter(filepath: Path, project_name: str) -> list:
    """对单个章节文件执行全部校验"""
    all_issues = []
    content = filepath.read_text(encoding="utf-8")

    all_issues.extend(check_leading_blank_lines(filepath))
    all_issues.extend(check_terminology(content, filepath, project_name))
    all_issues.extend(check_character_names(content, filepath, project_name))
    all_issues.extend(check_zero_dialogue_format(content, filepath))
    all_issues.extend(check_grade_format(content, filepath))
    all_issues.extend(check_dialogue_continuity(content, filepath))
    all_issues.extend(check_special_chars(content, filepath))
    all_issues.extend(check_chapter_file_integrity(filepath, project_name))

    return all_issues


def main():
    parser = argparse.ArgumentParser(description="上下文一致性校验工具")
    parser.add_argument("--project", type=str, default="",
                        help="项目名（如 全球灾变：我的AI能自动升级）")
    parser.add_argument("--chapter", type=str, default="",
                        help="指定章节文件名，不指定则校验全部章节")
    parser.add_argument("--fix", action="store_true",
                        help="自动修复可修复的问题（术语替换、首行空行）")
    parser.add_argument("--verbose", action="store_true",
                        help="详细输出模式")
    args = parser.parse_args()

    if not args.project:
        print("错误: 请指定 --project 参数")
        print("示例: python 脚本/上下文校验.py --project 全球灾变：我的AI能自动升级")
        sys.exit(1)

    project_dir = PROJECT_ROOT / args.project / "执行" / "章节"
    if not project_dir.exists():
        print(f"错误: 项目目录不存在: {project_dir}")
        sys.exit(1)

    chapter_files = []
    if args.chapter:
        chapter_path = project_dir / args.chapter
        if chapter_path.exists():
            chapter_files.append(chapter_path)
        else:
            print(f"错误: 章节文件不存在: {chapter_path}")
            sys.exit(1)
    else:
        chapter_files = sorted(project_dir.glob("第*.md"))

    print(f"\n{'='*60}")
    print(f"  上下文一致性校验: {args.project}")
    print(f"  章节文件数: {len(chapter_files)}")
    print(f"  自动修复: {'开启' if args.fix else '关闭'}")
    print(f"{'='*60}\n")

    total_issues = 0
    fixed_count = 0

    for cf in chapter_files:
        issues = validate_chapter(cf, args.project)
        if issues:
            print(f"\n  📄 {cf.name}")
            for issue in issues:
                total_issues += 1
                print(f"    ⚠️  [L{issue['line']}] {issue['type']}")
                print(f"        {issue['detail']}")

                if args.fix:
                    if issue["type"].startswith("术语错误"):
                        wrong_term = issue["type"].split("→")[0].replace("术语错误: ", "")
                        correct_term = issue["type"].split("→")[1]
                        content = cf.read_text(encoding="utf-8")
                        if wrong_term in content:
                            content = content.replace(wrong_term, correct_term)
                            cf.write_text(content, encoding="utf-8")
                            fixed_count += 1
                            print(f"        ✅ 已修复: {wrong_term} → {correct_term}")
                    elif issue["type"] == "首行空行":
                        content = cf.read_text(encoding="utf-8")
                        stripped = content.lstrip("\n\r")
                        if stripped != content:
                            cf.write_text(stripped, encoding="utf-8")
                            fixed_count += 1
                            print(f"        ✅ 已修复: 删除首行空行")

    print(f"\n{'='*60}")
    print(f"  校验完成")
    print(f"  总问题数: {total_issues}")
    if args.fix:
        print(f"  已修复: {fixed_count}")
    print(f"{'='*60}\n")

    return total_issues


if __name__ == "__main__":
    sys.exit(main())