#!/usr/bin/env python3
"""
工具函数集
==========
供 Agent 调用的三个核心工具函数：
  1. read_project_file(file_path)     — 读取项目中的任意文件
  2. write_chapter_file(novel_name, chapter_num, content) — 写入章节文件
  3. publish_to_platform(novel_name, chapter_path) — 发布章节到番茄小说

用法（被 Agent 导入调用）：
    from 脚本.tools import read_project_file, write_chapter_file, publish_to_platform
"""

import re
import os
import sys
import yaml
import logging
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ============================================================
# 1. 读取项目文件
# ============================================================

def read_project_file(file_path: str) -> str:
    """读取指定路径的文件内容。

    支持：
      - 绝对路径（如 /Users/.../大纲.md）
      - 相对于项目根目录的路径（如 策划/大纲.md）
      - 相对于小说目录的路径（如 执行/章节/第001章·觉醒.md）

    Args:
        file_path: 文件路径（绝对或相对）

    Returns:
        文件内容的字符串

    Raises:
        FileNotFoundError: 文件不存在
    """
    path = Path(file_path)

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    path = path.resolve()

    if not path.exists():
        rel = Path(file_path)
        # 尝试相对于项目根目录
        candidate = PROJECT_ROOT / rel
        if candidate.exists():
            path = candidate
        else:
            # 尝试在小说项目子目录中查找（策划/、记忆/ 通常在各小说文件夹内）
            found = False
            for novel_dir in PROJECT_ROOT.iterdir():
                if not novel_dir.is_dir() or novel_dir.name.startswith("."):
                    continue
                candidate = novel_dir / rel
                if candidate.exists():
                    path = candidate
                    found = True
                    break
            if not found:
                # 最后一次尝试：按文件名搜索
                target_name = rel.name
                for novel_dir in PROJECT_ROOT.iterdir():
                    if not novel_dir.is_dir() or novel_dir.name.startswith("."):
                        continue
                    for match in novel_dir.rglob(target_name):
                        path = match
                        found = True
                        break
                    if found:
                        break
            if not found:
                raise FileNotFoundError(
                    f"文件不存在: {file_path}\n"
                    f"  已尝试:\n"
                    f"    绝对路径: {Path(file_path).resolve()}\n"
                    f"    项目根目录: {PROJECT_ROOT / rel}\n"
                    f"    各小说子目录: 未找到\n"
                    f"  项目根路径: {PROJECT_ROOT}"
                )

    content = path.read_text(encoding="utf-8")
    log.info(f"已读取文件: {path.relative_to(PROJECT_ROOT)}（{len(content)} 字符）")
    return content


# ============================================================
# 2. 写入章节文件
# ============================================================

def write_chapter_file(novel_name: str, chapter_num: int, content: str, title: str = "") -> str:
    """将章节正文写入小说的 执行/章节/ 目录中。

    文件名的格式为：第{num:03d}章·{title}.md
    标题优先使用传入的 title 参数；如果未传入，则从 content 正文中自动提取。

    Args:
        novel_name:  小说项目文件夹名称
        chapter_num: 章节号
        content:     章节正文
        title:       章节标题（可选。不传则从正文自动提取）

    Returns:
        写入后的文件绝对路径字符串
    """
    novel_dir = PROJECT_ROOT / novel_name
    chapters_dir = novel_dir / "执行" / "章节"

    if not chapters_dir.exists():
        chapters_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"已创建章节目录: {chapters_dir}")

    # 标题：优先使用传入的，否则从正文提取
    if not title:
        title = extract_title(content, chapter_num)

    filename = f"第{chapter_num:03d}章·{title}.md"
    filepath = chapters_dir / filename

    filepath.write_text(content.strip() + "\n", encoding="utf-8")
    log.info(f"已写入章节: {filepath.relative_to(PROJECT_ROOT)}（{len(content)} 字符）")

    return str(filepath.resolve())


def extract_title(content: str, chapter_num: int) -> str:
    """从章节正文中提取标题。

    提取逻辑：
      1. 去除首尾空白
      2. 取第一段文字的前 4-10 个中文字符
      3. 如果提取失败或长度不足，返回默认标题

    Args:
        content:     章节正文
        chapter_num: 章节号（用于默认标题）

    Returns:
        标题字符串
    """
    text = content.strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if lines:
        first_line = lines[0]
        chinese_chars = re.findall(r"[\u4e00-\u9fff]+", first_line)
        if chinese_chars:
            combined = "".join(chinese_chars)
            title = combined[:8]
            if len(title) >= 2:
                return title

    # 如果首行没提取到，尝试从全文提取
    all_chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    if all_chinese:
        for segment in all_chinese:
            if len(segment) >= 3:
                return segment[:8]

    return f"第{chapter_num}章"


# ============================================================
# 3. 发布章节到番茄小说
# ============================================================

def publish_to_platform(novel_name: str, chapter_path: str) -> str:
    """将指定章节文件发布到番茄小说作家后台。

    流程：
      1. 加载该小说对应的发布配置（发布配置-{项目名}.yaml）
      2. 解析章节文件，提取章节号、标题和正文
      3. 实例化 FanqiePublisher 并执行发布
      4. 返回发布结果状态

    Args:
        novel_name:   小说名称（用于匹配发布配置）
        chapter_path: 章节文件的绝对路径

    Returns:
        发布结果状态字符串，如：
          "SUCCESS: 第67章《冻土之约》发布完成"
          "ERROR: 发布失败，原因：..."
    """
    chapter_file = Path(chapter_path)
    if not chapter_file.exists():
        return f"ERROR: 章节文件不存在: {chapter_path}"

    # 解析章节号
    parsed = parse_chapter_file(chapter_file)
    if not parsed:
        return f"ERROR: 无法解析章节文件: {chapter_file.name}"
    chapter_num, chapter_title = parsed

    # 读取正文
    content = chapter_file.read_text(encoding="utf-8").strip()

    # 加载发布配置
    config = load_novel_config(novel_name)
    if not config:
        return f"ERROR: 未找到小说 '{novel_name}' 的发布配置"

    # 确保 Chrome profile 目录存在
    browser_config = config.get("浏览器", {})
    profile_dir_config = browser_config.get("用户数据目录", "")
    if profile_dir_config:
        profile_path = Path(profile_dir_config)
        if not profile_path.is_absolute():
            profile_path = PROJECT_ROOT / profile_path
        profile_path.mkdir(parents=True, exist_ok=True)

    # 导入并实例化发布器
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from 自动化.发布器.发布器 import FanqiePublisher

        publisher = FanqiePublisher(config)
    except Exception as e:
        return f"ERROR: 发布器初始化失败: {e}"

    try:
        log.info(f"正在发布: 第{chapter_num}章 {chapter_title}（{novel_name}）")

        publisher.start()

        if not publisher.navigate_to_work():
            publisher.quit()
            return "ERROR: 无法进入作家工作台（请确认已在 Chrome 中登录番茄小说）"

        success = publisher.publish_chapter(chapter_num, chapter_title, content)

        if success:
            record_published(novel_name, chapter_num, chapter_title)
            result = f"SUCCESS: 第{chapter_num}章《{chapter_title}》发布完成"
        else:
            result = f"ERROR: 第{chapter_num}章《{chapter_title}》发布失败（详见日志）"

        publisher.quit()
        log.info(result)
        return result

    except Exception as e:
        try:
            publisher.quit()
        except Exception:
            pass
        return f"ERROR: 发布过程异常: {e}"


def parse_chapter_file(filepath: Path) -> Optional[tuple]:
    """解析章节文件，提取章节号和标题。

    支持的文件名格式：
      - 第067章·冻土之约.md
      - 第67章-冻土之约.md
      - 第67章 冻土之约.md

    Returns:
        (章节号, 标题) 或 None
    """
    pattern = r"^第(\d+)章[·\.,，、\s\-]*(.+)\.md$"
    match = re.match(pattern, filepath.name)
    if not match:
        return None
    return int(match.group(1)), match.group(2).strip()


def load_novel_config(novel_name: str) -> Optional[dict]:
    """加载小说的发布配置。

    优先查找：
      1. 发布配置-{novel_name}.yaml
      2. 发布配置.yaml（作为 fallback）

    Args:
        novel_name: 小说名称

    Returns:
        配置字典，或 None（未找到）
    """
    config_dir = PROJECT_ROOT / "自动化" / "配置"

    # 优先匹配精确命名
    exact = config_dir / f"发布配置-{novel_name}.yaml"
    if exact.exists():
        with open(exact, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # 次优：遍历匹配文件名包含关键词
    for f in sorted(config_dir.glob("发布配置-*.yaml"), reverse=True):
        if novel_name in f.stem:
            with open(f, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)

    # fallback：默认配置
    default = config_dir / "发布配置.yaml"
    if default.exists():
        with open(default, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            book_name = config.get("作品", {}).get("书名", "")
            if novel_name in book_name or book_name in novel_name:
                return config

    log.warning(f"未找到小说 '{novel_name}' 的发布配置")
    return None


def record_published(novel_name: str, chapter_num: int, title: str):
    """记录章节已发布状态到日志文件。"""
    from datetime import datetime
    log_dir = PROJECT_ROOT / "自动化" / "日志"
    log_dir.mkdir(parents=True, exist_ok=True)

    record_file = log_dir / f"已发布章节_{novel_name}.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(record_file, "a", encoding="utf-8") as f:
        f.write(f"{chapter_num}\t{title}\t{timestamp}\n")


# ============================================================
# 命令行入口（方便调试）
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="工具函数集 - 命令行入口")
    parser.add_argument("action", choices=["read", "write", "publish"], help="操作类型")
    parser.add_argument("--file", type=str, help="文件路径（read / publish 用）")
    parser.add_argument("--novel", type=str, default="万古神龙：我的血脉全靠吞", help="小说名称")
    parser.add_argument("--chapter", type=int, help="章节号（write 用）")
    parser.add_argument("--content", type=str, help="章节内容（write 用，文件路径或文本）")

    args = parser.parse_args()

    if args.action == "read":
        if not args.file:
            print("错误: --file 参数必填")
            sys.exit(1)
        print(read_project_file(args.file))

    elif args.action == "write":
        if not args.chapter:
            print("错误: --chapter 参数必填")
            sys.exit(1)
        content = args.content or "# 空白章节"
        result = write_chapter_file(args.novel, args.chapter, content)
        print(f"已写入: {result}")

    elif args.action == "publish":
        if not args.file:
            print("错误: --file 参数必填")
            sys.exit(1)
        result = publish_to_platform(args.novel, args.file)
        print(result)
