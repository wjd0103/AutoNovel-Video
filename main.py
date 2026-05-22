#!/usr/bin/env python3
"""
《万古神龙：我的血脉全靠吞》— 创作入口
========================================
由 NovelKingdomHarness（ReAct 多 Agent 导演系统）驱动，
支持单章创作与批量连续创作。

用法：
    # 创作单个章节
    python main.py --target 78

    # 批量创作第78-87章（共10章）
    python main.py --batch --start 78 --end 87
"""

import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from 自动化.agent_director import NovelKingdomHarness


def run_single(novel: str, target: int) -> str:
    """运行单个章节的创作流程。"""
    print(f"\n{'='*60}")
    print(f"  开始创作第 {target} 章")
    print(f"{'='*60}")

    harness = NovelKingdomHarness(
        novel_name=novel,
        target_chapter=target,
    )

    summary = harness.start_work()

    print()
    print("=" * 60)
    print(f"  第 {target} 章创作完成")
    print(summary)
    print("=" * 60)

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="《万古神龙：我的血脉全靠吞》— 创作入口"
    )
    parser.add_argument(
        "--novel",
        type=str,
        default="万古神龙：我的血脉全靠吞",
        help="小说名称（文件夹名）",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=78,
        help="目标章节号（单章模式）",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="批量模式",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=78,
        help="批量起始章节号",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=87,
        help="批量结束章节号（含）",
    )
    args = parser.parse_args()

    if args.batch:
        print(f"\n{'='*60}")
        print(f"  批量创作模式")
        print(f"  小说: {args.novel}")
        print(f"  范围: 第{args.start}章 ~ 第{args.end}章（共{args.end - args.start + 1}章）")
        print(f"{'='*60}")

        for ch in range(args.start, args.end + 1):
            summary = run_single(args.novel, ch)
            if "已生成内容: ❌" in summary:
                print(f"  ⚠️ 第 {ch} 章生成失败，终止批量流程")
                break
            # 章节间短暂停顿，避免 API 限流
            if ch < args.end:
                time.sleep(3)

        print(f"\n{'='*60}")
        print(f"  批量创作全部完成")
        print(f"  范围: 第{args.start}章 ~ 第{args.end}章")
        print(f"{'='*60}")

    else:
        run_single(args.novel, args.target)


if __name__ == "__main__":
    main()
