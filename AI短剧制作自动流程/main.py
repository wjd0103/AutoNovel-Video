"""AI短剧制作自动流程 —— 4 步流水线入口

Step 1/4  读取小说原文 → 全剧设定 + 分集大纲
Step 2/4  按每集生成详细分镜（镜头/景别/画面/时长/音频/备注）
Step 3/4  分镜描述 → 视频生成 Prompt → 调用 API 生成
Step 4/4  各镜视频合并 → 完整短剧成片

用法:
  python main.py                                # 使用默认 sample_novel.txt
  python main.py --input chapters/ch1.txt       # 指定输入文件
  python main.py --title "我的短剧"              # 指定短剧名称
  python main.py --dry-run                      # 干跑模式（跳过 API 调用）
  python main.py --episodes 3                   # 指定分集数
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# 日志
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# ═══════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "测试" / "sample_novel.txt"


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

SEPARATOR = "━" * 50
TOTAL_PHASES = 4


def _banner(text: str) -> None:
    print()
    print(SEPARATOR)
    print(f"  {text}")
    print(SEPARATOR)


def _phase(phase: int, total: int, text: str) -> None:
    print()
    print(f"◆  [Phase {phase}/{total}]  {text}")
    print("─" * 50)


def _done(text: str = "完成") -> None:
    print(f"  ✅ {text}")


def _skip(text: str = "跳过") -> None:
    print(f"  ⏭  {text}")


def _fail(text: str) -> None:
    print(f"  ❌ {text}")


def _info(text: str) -> None:
    print(f"     {text}")


# ═══════════════════════════════════════════════════════════════
# 确认节点辅助
# ═══════════════════════════════════════════════════════════════


def _print_menu(title: str, options: list[str]) -> str:
    """打印交互菜单，返回用户选择"""
    print()
    print(f"  {'═' * 48}")
    print(f"  ⚠  {title}")
    print(f"  {'═' * 48}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    print()
    while True:
        try:
            choice = input(f"  请输入选项 (1-{len(options)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except (ValueError, IndexError):
            pass
        print(f"  无效输入，请输入 1-{len(options)} 之间的数字")


def _confirm_character_portraits(asset_library, script_title: str) -> None:
    """确认节点：让用户确认/替换/上传角色参考图"""
    from 核心.asset_library import AssetLibrary
    from 核心.剧本.script_models import SCRIPT_DIR
    from 核心.资产.image_generator import CharacterPortraitGenerator, CHAR_REF_DIR

    print()
    _info("─" * 40)
    _info("【确认节点】角色肖像参考图确认")
    _info("─" * 40)

    # 列出当前状态
    has_all_images = True
    for ch in asset_library.characters:
        ref_path = ch.reference_image_path
        if ref_path and Path(ref_path).is_file():
            _info(f"  ✅ {ch.name}: {Path(ref_path).name}  ({Path(ref_path).stat().st_size // 1024} KB)")
        else:
            has_all_images = False
            _info(f"  ⚠️  {ch.name}: 暂无参考图")

    choice = _print_menu(
        f"角色肖像图确认 — {script_title}",
        [
            "使用当前图片，继续",
            "手动指定新图片路径（替换部分角色）",
            "查看角色描述后重新选择",
            "跳过角色参考图（不使用角色固定）",
        ],
    )

    if choice == "跳过角色参考图（不使用角色固定）":
        for ch in asset_library.characters:
            ch.reference_image_path = ""
        _info("已清空所有角色参考图")
        asset_path = SCRIPT_DIR / f"{script_title}_视觉资产库.json"
        asset_library.save(asset_path)
        return

    if "手动指定新图片路径" in choice:
        print()
        _info("请输入每个角色对应的图片路径（留空=保持不变，输入 skip=跳过该角色）:")
        print()
        for ch in asset_library.characters:
            current = ch.reference_image_path or "（无）"
            print(f"  {ch.name}: 当前路径 = {current}")
            inp = input(f"  → 新路径: ").strip()
            if inp.lower() == "skip":
                ch.reference_image_path = ""
                _info(f"  ✅ 已清空 {ch.name} 的参考图")
            elif inp and Path(inp).is_file():
                ch.reference_image_path = inp
                _info(f"  ✅ {ch.name} → {Path(inp).name}")
            elif inp:
                _info(f"  ⚠️  文件不存在: {inp}，保持不变")
        asset_path = SCRIPT_DIR / f"{script_title}_视觉资产库.json"
        asset_library.save(asset_path)
        _info("资产库已更新")
        return

    if "查看角色描述" in choice or "重新选择" in choice:
        print()
        _info("角色外貌描述（供你手动准备参考图参考）:")
        for ch in asset_library.characters:
            print(f"\n  ── {ch.name} ──")
            print(f"  外貌: {ch.appearance}")
            print(f"  穿着: {ch.clothing or '（无特定）'}")
            print(f"  英文关键词: {ch.visual_keywords_en}")
        print()
        _confirm_character_portraits(asset_library, script_title)
        return

    # 使用当前图片 —— 检查是否缺少图片，如果缺少可以尝试自动生成
    if not has_all_images:
        gen = CharacterPortraitGenerator()
        if gen.enabled:
            choice2 = _print_menu(
                "部分角色缺少参考图",
                ["自动生成缺失的角色肖像", "跳过，不使用参考图"],
            )
            if "自动生成" in choice2:
                _info("正在生成缺失角色肖像…")
                missing = {ch.name for ch in asset_library.characters if not ch.reference_image_path or not Path(ch.reference_image_path).is_file()}
                for ch in asset_library.characters:
                    if ch.name in missing:
                        try:
                            path = gen._generate_one(ch)
                            ch.reference_image_path = str(path)
                            _info(f"  ✅ {ch.name} 已生成")
                        except Exception as e:
                            _info(f"  ❌ {ch.name} 生成失败: {e}")
                asset_path = SCRIPT_DIR / f"{script_title}_视觉资产库.json"
                asset_library.save(asset_path)
        else:
            _info("IMAGE_API_KEY 未配置，无法自动生成")
            for ch in asset_library.characters:
                if not ch.reference_image_path or not Path(ch.reference_image_path).is_file():
                    ch.reference_image_path = ""

    # 最终汇总
    _info("最终角色肖像配置:")
    for ch in asset_library.characters:
        if ch.reference_image_path and Path(ch.reference_image_path).is_file():
            _info(f"  ✅ {ch.name}: {Path(ch.reference_image_path).name}")
        else:
            _info(f"  ⏭  {ch.name}: 无参考图")


def _confirm_video_result(output_path: Path, label: str) -> bool:
    """确认节点：让用户确认生成结果"""
    print()
    _info("─" * 40)
    _info(f"【确认节点】{label}")
    _info("─" * 40)

    if output_path.is_file():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        _info(f"  文件: {output_path.name}")
        _info(f"  大小: {size_mb:.1f} MB")
    else:
        _info(f"  文件不存在: {output_path}")

    choice = _print_menu(
        label,
        ["✅ 确认通过，继续下一阶段", "⏹  停止流水线"],
    )
    if "停止" in choice:
        _info("用户选择停止，流水线结束")
        sys.exit(0)
    return True


# ═══════════════════════════════════════════════════════════════
# 阶段一：读取小说原文
# ═══════════════════════════════════════════════════════════════


def phase_read_text(path: Path) -> str:
    _phase(1, TOTAL_PHASES, "读取小说原文")
    if not path.is_file():
        _fail(f"文件不存在: {path}")
        sys.exit(1)

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        _fail("文件内容为空")
        sys.exit(1)

    _info(f"来源: {path.name}")
    _info(f"字数: {len(raw):,}")
    _done()

    preview = raw[:120].replace("\n", " ")
    _info(f"前 120 字预览: 「{preview}…」")
    return raw


# ═══════════════════════════════════════════════════════════════
# 阶段二：全剧设定 + 分集大纲
# ═══════════════════════════════════════════════════════════════


def phase_outline(
    novel_text: str,
    series_title: str,
    dry_run: bool,
) -> tuple:
    _phase(2, TOTAL_PHASES, "正在生成全剧设定 & 分集大纲")

    if dry_run:
        _skip("干跑模式：使用模拟剧本大纲")
        script = _mock_outline(series_title)
        # 干跑也保存资产库用于后续验证
        from 核心.asset_library import extract_asset_library
        from 核心.剧本.script_models import SCRIPT_DIR
        library = extract_asset_library(script)
        asset_path = SCRIPT_DIR / f"{script.settings.title}_视觉资产库.json"
        library.save(asset_path)
        _info(f"视觉资产库已保存: {asset_path.name}")
        return script

    from 核心.剧本.outline_agent import generate_outline
    from 核心.剧本.script_parser import save_series_script, save_series_script_markdown
    from 核心.asset_library import extract_asset_library

    logger.info("开始调用 DeepSeek 生成剧本大纲…")
    t0 = time.perf_counter()
    script = generate_outline(novel_text, series_title=series_title)
    elapsed = time.perf_counter() - t0

    _done(f"生成 | 耗时 {elapsed:.1f}s")
    _info(f"短剧名: {script.settings.title}")
    _info(f"风格: {script.settings.genre} | 视觉: {script.settings.visual_style}")
    _info(f"角色: {len(script.settings.characters)} 人")
    _info(f"分集: {len(script.episodes)} 集")

    for ep in script.episodes:
        _info(f"  第{ep.episode_number}集 · {ep.title}  {ep.estimated_duration}")

    json_path = save_series_script(script)
    md_path = save_series_script_markdown(script)
    _info(f"剧本已保存: {json_path.parent.name}/{json_path.name}")
    _info(f"大纲已保存: {md_path.parent.name}/{md_path.name}")

    # ── 提取并保存全局视觉资产库 ──
    from 核心.剧本.script_models import SCRIPT_DIR
    library = extract_asset_library(script)
    asset_path = SCRIPT_DIR / f"{script.settings.title}_视觉资产库.json"
    library.save(asset_path)
    _info(f"视觉资产库已保存: {asset_path.name} ({len(library.characters)} 角色, {len(library.scenes)} 场景)")
    _info("─" * 40)
    _info("资产库前缀示例（将自动拼入每个镜头 Prompt）：")
    prefix_preview = library.build_global_prefix()[:100].replace("\n", " ")
    _info(f"  {prefix_preview}…")

    # ── 生成角色肖像（供 Seedance 角色参考图使用）──
    if not dry_run:
        from 核心.资产.image_generator import CharacterPortraitGenerator
        gen = CharacterPortraitGenerator()
        if gen.enabled:
            _info("正在生成角色参考肖像…")
            portrait_map = gen.generate_all(library)
            if portrait_map:
                library.update_reference_images(portrait_map)
                library.save(asset_path)
                _info(f"角色肖像已生成: {len(portrait_map)} 张 → {list(portrait_map.values())[0].parent.name}")
                for name, p in portrait_map.items():
                    _info(f"  {name}: {p.name}")
        else:
            _info("IMAGE_API_KEY 未配置，跳过角色肖像生成")
    else:
        _info("干跑模式：跳过角色肖像生成")

    return script


def _mock_outline(series_title: str):
    from 核心.剧本.script_models import (
        CharacterSetting, EpisodeOutline, SceneSetting, ScriptSetting, SeriesScript,
    )

    return SeriesScript(
        settings=ScriptSetting(
            title=series_title or "模拟短剧",
            genre="都市悬疑",
            visual_style="赛博朋克霓虹色调",
            tags=["悬疑", "反转"],
            bgm_description="紧张电子配乐",
            characters=[
                CharacterSetting(name="林越", gender="男", appearance="黑色短发，灰色战术夹克",
                                 personality="冷静果断", voice_id="male_lead", voice_name="zh-CN-YunxiNeural"),
                CharacterSetting(name="赵绫", gender="女", appearance="棕色短发，灰绿色战术服",
                                 personality="直率勇敢", voice_id="female_lead", voice_name="zh-CN-XiaoxiaoNeural"),
            ],
            important_scenes=[
                SceneSetting(name="废墟街道", description="夜晚的废墟，月光照射，断壁残垣"),
                SceneSetting(name="安全区大门", description="巨大的金属门，探照灯扫射"),
            ],
        ),
        episodes=[
            EpisodeOutline(episode_number=1, title="黑暗中的猎手",
                           outline="林越和赵绫在废墟中猎杀变异体，遇到安全区委员会的紧急任务。",
                           estimated_duration="3-5分钟", cliffhanger="一只领主级变异体正在逼近安全区。",
                           chapter_range="第1章"),
            EpisodeOutline(episode_number=2, title="领主来袭",
                           outline="安全区面临领主级变异体的威胁，众人制定作战计划。",
                           estimated_duration="3-5分钟", cliffhanger="沈薇发现了一个惊人的秘密。",
                           chapter_range="第2-3章"),
        ],
    )


# ═══════════════════════════════════════════════════════════════
# 阶段三：按集生成分镜
# ═══════════════════════════════════════════════════════════════


def phase_storyboard(
    script,
    novel_text: str,
    dry_run: bool,
) -> list:
    _phase(3, TOTAL_PHASES, "正在按集生成详细分镜")

    from 核心.storyboard_agent import ShotStoryboardAgent
    from 核心.剧本.script_parser import save_episode_storyboard

    series_setting_json = ""
    if script and not dry_run:
        series_setting_json = script.settings.model_dump_json(indent=2, ensure_ascii=False)

    agent = ShotStoryboardAgent()
    all_storyboards = []

    episodes_to_process = script.episodes if script else []
    if not episodes_to_process:
        _skip("无分集数据")
        return all_storyboards

    for ep in episodes_to_process:
        _info(f"正在处理 第{ep.episode_number}集 · {ep.title}")

        if dry_run:
            from 核心.storyboard_agent import EpisodeStoryboard, ShotModel
            storyboard = EpisodeStoryboard(
                episode_number=ep.episode_number,
                episode_title=ep.title,
                shots=[
                    ShotModel(id=1, camera_movement="固定", shot_type="远景",
                              scene_content="模拟画面内容", duration=4.0,
                              audio_content="模拟音频", notes="", character_list=["林越"]),
                ],
            )
        else:
            t0 = time.perf_counter()
            storyboard = agent.run(
                novel_text,
                episode_number=ep.episode_number,
                episode_title=ep.title,
                series_setting=series_setting_json,
            )
            elapsed = time.perf_counter() - t0
            _info(f"  生成 {len(storyboard.shots)} 个分镜 | 耗时 {elapsed:.1f}s")

        json_path, md_path = save_episode_storyboard(storyboard)
        _info(f"  分镜已保存: {md_path}")
        all_storyboards.append(storyboard)

    _done(f"全部 {len(all_storyboards)} 集分镜生成完成")
    return all_storyboards


# ═══════════════════════════════════════════════════════════════
# 阶段四：生成 Prompt 并模拟调用视频生成
# ═══════════════════════════════════════════════════════════════


def phase_prompts(
    storyboards: list,
    script,
    dry_run: bool,
) -> None:
    _phase(4, TOTAL_PHASES, "正在生成视频 Prompt 并输出（前置资产库前缀）")

    from 核心.prompt_generator import PromptGenerator
    from 核心.剧本.script_models import EPISODE_DIR, SCRIPT_DIR
    from 核心.asset_library import AssetLibrary

    # ── 从 JSON 加载之前保存的全局视觉资产库 ──
    asset_library = None
    if script:
        asset_path = SCRIPT_DIR / f"{script.settings.title}_视觉资产库.json"
        if asset_path.is_file():
            asset_library = AssetLibrary.load(asset_path)
            _info(f"已加载视觉资产库: {asset_path.name}")
        else:
            _info("视觉资产库文件不存在，使用传统模式")

    # 旧模式 fallback：从 script 直接取角色数据
    characters_data = []
    if script and not asset_library:
        for ch in script.settings.characters:
            characters_data.append({
                "name": ch.name,
                "appearance": ch.appearance,
                "voice_id": ch.voice_id,
                "voice_name": ch.voice_name,
            })

    generator = PromptGenerator(
        visual_style=script.settings.visual_style if script else "anime style",
        characters=characters_data if characters_data else None,
        asset_library=asset_library,
    )

    total_shots = 0
    for storyboard in storyboards:
        ep_dir = EPISODE_DIR / f"第{storyboard.episode_number:02d}集"
        ep_dir.mkdir(parents=True, exist_ok=True)

        plans = generator.generate_episode_plans(storyboard)
        total_shots += len(plans)

        prompt_path = ep_dir / "视频Prompt.json"
        prompt_path.write_text(
            json.dumps([p.model_dump() for p in plans], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        md_path = ep_dir / "视频Prompt.md"
        md_lines = [f"# 第{storyboard.episode_number}集 · {storyboard.episode_title} —— 视频 Prompt", "", "| 镜号 | 时长 | 配音 | Prompt |", "|------|------|------|-------|"]
        for p in plans:
            prompt_short = p.image_prompt[:80] + "…" if len(p.image_prompt) > 80 else p.image_prompt
            md_lines.append(f"| {p.shot_id} | {p.duration}s | {p.voice_id} | {prompt_short} |")
        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        _info(f"  第{storyboard.episode_number}集: {len(plans)} 个 Prompt 已保存")

        if dry_run:
            _skip("干跑模式：跳过实际 API 调用")
        else:
            _info(f"  提示: 可将 Prompt 发送到视频生成 API 生成视频片段")

    _done(f"共 {len(storyboards)} 集 {total_shots} 个镜头 Prompt")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI短剧制作自动流程 —— 小说→剧本→分镜→Prompt→视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py
  python main.py --input chapters/ch01.txt --title "我的短剧"
  python main.py --dry-run
  python main.py --no-confirm                   # 非交互模式，跳过确认节点
        """,
    )
    parser.add_argument(
        "--input", "-i", type=Path, default=DEFAULT_INPUT,
        help=f"输入小说文件路径 (默认: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--title", "-t", type=str, default="",
        help="短剧名称 (留空由 DeepSeek 自动生成)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式：跳过所有 API 调用，验证配置和代码完整性",
    )
    parser.add_argument(
        "--episodes", type=int, default=0,
        help="手动指定分集数（0 表示由 AI 自动决定）",
    )
    parser.add_argument(
        "--no-confirm", action="store_true",
        help="非交互模式：跳过所有确认节点",
    )
    args = parser.parse_args()

    # ── 启动 ────────────────────────────────────────────────
    total_start = time.perf_counter()

    print()
    print("╔" + "═" * 48 + "╗")
    print("║" + "    🎬  AI短剧制作自动流程".ljust(37) + "║")
    print("║" + f"    输入: {args.input.name}".ljust(37) + "║")
    mode = "DRY-RUN (不调用 API)" if args.dry_run else "正式运行"
    print("║" + f"    模式: {mode}".ljust(37) + "║")
    if args.title:
        print("║" + f"    短剧: {args.title}".ljust(37) + "║")
    if args.no_confirm:
        print("║" + "    确认: 跳过（非交互模式）".ljust(37) + "║")
    print("╚" + "═" * 48 + "╝")
    print()

    # ── Phase 1: 读取原文 ────────────────────────────────
    novel_text = phase_read_text(args.input)

    # ── Phase 2: 全剧设定 + 分集 ──────────────────────────
    series_script = phase_outline(
        novel_text,
        series_title=args.title,
        dry_run=args.dry_run,
    )

    # ── 确认节点 A：角色肖像确认 ─────────────────────────
    if not args.dry_run and not args.no_confirm:
        from 核心.剧本.script_models import SCRIPT_DIR
        from 核心.asset_library import AssetLibrary
        asset_path = SCRIPT_DIR / f"{series_script.settings.title}_视觉资产库.json"
        if asset_path.is_file():
            asset_lib = AssetLibrary.load(asset_path)
            _confirm_character_portraits(asset_lib, series_script.settings.title)

    # ── Phase 3: 按集分镜 ────────────────────────────────
    storyboards = phase_storyboard(
        series_script,
        novel_text,
        dry_run=args.dry_run,
    )

    # ── 确认节点 B：视频生成前确认肖像（如果之前没确认过）──
    if not args.dry_run and not args.no_confirm:
        from 核心.剧本.script_models import SCRIPT_DIR
        from 核心.asset_library import AssetLibrary
        asset_path = SCRIPT_DIR / f"{series_script.settings.title}_视觉资产库.json"
        if asset_path.is_file():
            asset_lib = AssetLibrary.load(asset_path)
            has_refs = any(
                ch.reference_image_path and Path(ch.reference_image_path).is_file()
                for ch in asset_lib.characters
            )
            if has_refs:
                _info("视频生成前角色肖像确认：")
                for ch in asset_lib.characters:
                    if ch.reference_image_path and Path(ch.reference_image_path).is_file():
                        _info(f"  ✅ {ch.name}: {Path(ch.reference_image_path).name}")
                choice = _print_menu(
                    "确认角色参考图（将随每个镜头传入 Seedance API）",
                    ["确认使用，开始生成视频", "重新选择肖像", "跳过参考图"],
                )
                if "重新选择" in choice:
                    _confirm_character_portraits(asset_lib, series_script.settings.title)
                elif "跳过" in choice:
                    for ch in asset_lib.characters:
                        ch.reference_image_path = ""
                    asset_lib.save(asset_path)
                    _info("已清空所有参考图")
            else:
                _info("无角色参考图，直接继续")

    # ── Phase 4: Prompt + 视频生成 ──────────────────────
    phase_prompts(
        storyboards,
        series_script,
        dry_run=args.dry_run,
    )

    # ── 确认节点 C：生成结果确认 ─────────────────────────
    if not args.dry_run and not args.no_confirm:
        from 核心.剧本.script_models import EPISODE_DIR
        first_ep_dir = EPISODE_DIR / "第01集"
        video_dir = first_ep_dir / "视频"
        if video_dir.is_dir():
            videos = sorted(video_dir.glob("*.mp4"))
            if videos:
                _confirm_video_result(videos[0], "首集视频片段已生成")
            else:
                _confirm_video_result(first_ep_dir / "视频Prompt.json", "视频 Prompt 已生成")

    # ── 汇总 ────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start

    total_episodes = len(series_script.episodes) if series_script else 0
    total_shots = sum(len(s.shots) for s in storyboards) if storyboards else 0

    print()
    print("╔" + "═" * 48 + "╗")
    print("║" + "    ✅  流水线执行完毕".ljust(44) + "║")
    print("║" + f"    总耗时: {total_elapsed:.1f}s".ljust(39) + "║")
    print("║" + f"    分集: {total_episodes} 集".ljust(39) + "║")
    print("║" + f"    总镜数: {total_shots} 个".ljust(39) + "║")
    print("╚" + "═" * 48 + "╝")
    print()


if __name__ == "__main__":
    main()
