"""AI短剧制作自动流程 —— 总流水线入口

五阶段一键运行:
  Phase 1/5  读取小说原文
  Phase 2/5  DeepSeek 解析 → 分镜脚本 → 保存剧本
  Phase 3/5  并行下载 图片 & 配音资产（角色一致性）
  Phase 4/5  Seedance 图生视频
  Phase 5/5  视频合成 & 字幕叠加 → 最终 mp4

用法:
  python main.py                          # 使用默认 sample_novel.txt
  python main.py --input chapters/ch1.txt # 指定输入文件
  python main.py --series-title "第1集·觉醒"  # 指定剧集标题
  python main.py --dry-run                # 干跑模式（跳过 API 调用）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

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
PHASE_PREFIX = "◆  [Phase {phase}/{total}]"
TOTAL_PHASES = 5


def _banner(text: str) -> None:
    print()
    print(SEPARATOR)
    print(f"  {text}")
    print(SEPARATOR)


def _phase(phase: int, total: int, text: str) -> None:
    header = PHASE_PREFIX.format(phase=phase, total=total)
    print()
    print(f"{header}  {text}")
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
# 角色配置加载
# ═══════════════════════════════════════════════════════════════

def _load_characters(char_config_path: Optional[Path]) -> tuple[Optional[list[dict]], Optional[Path]]:
    """加载角色配置文件，返回 (角色列表, 文件路径)。

    支持 JSON 和 YAML 格式。YAML 需要 pyyaml。
    """
    if char_config_path is None:
        return None, None

    if not char_config_path.is_file():
        _fail(f"角色配置文件不存在: {char_config_path}")
        return None, None

    raw = char_config_path.read_text(encoding="utf-8")

    if char_config_path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            data = yaml.safe_load(raw)
        except ImportError:
            _fail("需要安装 pyyaml: pip install pyyaml")
            return None, None
    else:
        data = json.loads(raw)

    characters = data.get("characters", []) if isinstance(data, dict) else data
    _info(f"已加载 {len(characters)} 个角色定义")
    for ch in characters:
        _info(f"  {ch.get('voice_id')} → {ch.get('name')} (TTS: {ch.get('voice_name', 'default')})")
    return characters, char_config_path


def _update_character_refs(
    char_config_path: Optional[Path],
    characters: Optional[list[dict]],
    image_results: list,
    storyboard: "StoryboardModel" = None,
) -> bool:
    """首次生成后将成功的场景图片关联到角色配置的 reference_image 字段。"""
    if not char_config_path or not characters:
        return False

    updated = False
    for ch in characters:
        vid = ch.get("voice_id", "")
        if ch.get("reference_image", ""):
            continue

        scene_id = None
        if storyboard:
            for sc in storyboard.scenes:
                if sc.voice_id == vid or sc.voice_id == (vid + "_01"):
                    scene_id = sc.id
                    break

        if scene_id is None:
            continue

        for r in image_results:
            if r.success and r.scene_id == scene_id:
                ch["reference_image"] = str(r.path)
                logger.info("角色 %s (%s) 参考图: %s", ch.get("name"), vid, r.path.name)
                updated = True
                break

    if updated:
        _write_character_config(char_config_path, characters)
        _info("角色参考图已保存到配置文件")
    return updated


def _write_character_config(path: Path, characters: list[dict]) -> None:
    """写回角色配置文件（保留格式）。"""
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            data = {"characters": characters}
            path.write_text(yaml.safe_dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
            return
        except ImportError:
            pass

    path.write_text(
        json.dumps({"characters": characters}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
# 阶段二：调用 DeepSeek 生成分镜
# ═══════════════════════════════════════════════════════════════


def phase_storyboard(
    novel_text: str,
    series_title: str,
    dry_run: bool,
    characters: Optional[list[dict]] = None,
) -> "StoryboardModel":
    _phase(2, TOTAL_PHASES, "正在调用 DeepSeek 解析小说 → 分镜脚本")

    if dry_run:
        _skip("干跑模式：使用模拟分镜数据")
        from 核心.storyboard_agent import SceneModel, StoryboardModel

        return StoryboardModel(
            series_title=series_title or "模拟剧集",
            scenes=[
                SceneModel(
                    id=1, character_list=["主角"], image_prompt="anime style, consistent character design, cinematic lighting, a man standing in ruins at night",
                    dialogue="准备开火。", voice_id="male_lead", camera_movement="static",
                ),
                SceneModel(
                    id=2, character_list=["主角", "配角"], image_prompt="anime style, consistent character design, cinematic lighting, two people crouching behind rubble",
                    dialogue="这次能活下来吗？", voice_id="female_lead", camera_movement="zoom_in",
                ),
            ],
        )

    from 核心.storyboard_agent import generate_storyboard, save_script

    logger.info("开始调用 DeepSeek…")
    t0 = time.perf_counter()
    storyboard = generate_storyboard(novel_text, series_title=series_title, characters=characters)
    elapsed = time.perf_counter() - t0

    _done(f"生成 {len(storyboard.scenes)} 个分镜 | 耗时 {elapsed:.1f}s")
    _info(f"剧集标题: {storyboard.series_title}")

    for s in storyboard.scenes:
        cam = s.camera_movement
        _info(f"  #{s.id:02d}  [{cam:>9s}]  voice={s.voice_id:>12s}  「{s.dialogue[:30]}」")

    json_path, md_path = save_script(storyboard, series_title or storyboard.series_title)
    _info(f"剧本已保存: {json_path.name}")
    _info(f"审阅脚本: {md_path.name}")

    return storyboard


# ═══════════════════════════════════════════════════════════════
# 阶段三：并行下载资产
# ═══════════════════════════════════════════════════════════════


def phase_assets(
    storyboard: "StoryboardModel",
    dry_run: bool,
    max_workers: int,
    characters: Optional[list[dict]] = None,
) -> "AssetBatchResult":
    _phase(3, TOTAL_PHASES, f"正在并行下载图片 & 配音资产 (workers={max_workers})")

    if dry_run:
        _skip("干跑模式：跳过资产下载")
        from 核心.asset_manager import AssetBatchResult

        return AssetBatchResult(total_elapsed=0)

    from 核心.asset_manager import generate_assets

    logger.info("开始并行下载…")
    t0 = time.perf_counter()
    result = generate_assets(storyboard, max_workers=max_workers, characters=characters)
    elapsed = time.perf_counter() - t0

    _info(f"图片: {result.image_ok}/{result.scene_count} 成功")
    _info(f"音频: {result.audio_ok}/{result.scene_count} 成功")
    _info(f"耗时: {elapsed:.1f}s")

    # 失败详情
    for r in result.image_results + result.audio_results:
        if not r.success and r.error:
            _fail(f"scene_{r.scene_id:02d} {r.kind} 失败: {r.error[:100]}")

    if result.image_ok == 0 and result.audio_ok == 0:
        _fail("所有资产下载均失败，流水线终止")
        sys.exit(1)

    if result.image_ok == result.scene_count and result.audio_ok == result.scene_count:
        _done("全部资产下载成功")
    else:
        _skip(f"部分资产失败，继续合成…")

    return result


# ═══════════════════════════════════════════════════════════════
# 阶段四：Seedance 图生视频
# ═══════════════════════════════════════════════════════════════


def phase_video_clips(
    storyboard: "StoryboardModel",
    dry_run: bool,
) -> Optional[Path]:
    _phase(4, TOTAL_PHASES, "正在调用 Seedance 将图片转化为短视频片段")

    if dry_run:
        _skip("干跑模式：跳过 Seedance 视频生成")
        return None

    scenes_with_dialogue = [s for s in storyboard.scenes if s.dialogue.strip()]
    if not scenes_with_dialogue:
        _skip("无有效对话分镜，跳过视频生成")
        return None

    from core.video_generator import SeedanceGenerator, VIDEO_DIR

    gen = SeedanceGenerator()

    image_paths: list[Path] = []
    durations: list[float] = []
    prompts: list[str] = []
    ids: list[int] = []

    from moviepy import AudioFileClip

    for s in scenes_with_dialogue:
        img_p = Path("output/images") / f"scene_{s.id:02d}.png"
        aud_p = Path("output/audio") / f"scene_{s.id:02d}.mp3"
        if not img_p.is_file():
            continue

        dur = 3.0
        if aud_p.is_file():
            try:
                ac = AudioFileClip(str(aud_p))
                dur = ac.duration + 0.5
                ac.close()
            except Exception:
                pass

        motion_prompt = s.dialogue
        if s.camera_movement and s.camera_movement != "static":
            cam_cn = {
                "zoom_in": "镜头缓缓推进", "zoom_out": "镜头缓缓拉远",
                "pan_left": "镜头向左平移", "pan_right": "镜头向右平移",
                "tilt_up": "镜头向上摇", "tilt_down": "镜头向下摇",
            }
            motion_prompt = f"{cam_cn.get(s.camera_movement, '')}，{s.dialogue}"

        image_paths.append(img_p)
        durations.append(dur)
        prompts.append(motion_prompt)
        ids.append(s.id)

    if not image_paths:
        _skip("无可用图片，跳过视频生成")
        return None

    _info(f"提交 {len(image_paths)} 个视频生成任务…")
    result = gen.generate_clips(image_paths, durations, prompts, ids)

    _info(f"视频片段: {result.ok}/{len(image_paths)} 成功")
    if result.ok > 0:
        _info(f"输出目录: {VIDEO_DIR}")
    _info(f"耗时: {result.total_elapsed:.0f}s")

    for t in result.tasks:
        if t.status != "completed":
            _fail(f"scene_{t.scene_id:02d}  {t.status}: {t.error[:80]}")

    return VIDEO_DIR if result.ok > 0 else None


# ═══════════════════════════════════════════════════════════════
# 阶段五：视频合成
# ═══════════════════════════════════════════════════════════════


def phase_video(
    storyboard: "StoryboardModel",
    dry_run: bool,
    video_dir: Optional[Path] = None,
) -> Path:
    _phase(5, TOTAL_PHASES, "正在合成视频 & 字幕叠加")

    if dry_run:
        _skip("干跑模式：跳过视频合成")
        out = ROOT / "output" / "final" / "final_manju_video.mp4"
        _info(f"（模拟输出路径: {out}）")
        return out

    from 核心.video_compiler import VideoCompiler

    logger.info("开始视频合成…")
    t0 = time.perf_counter()

    compiler = VideoCompiler()
    output_path = compiler.compile(storyboard, video_dir=video_dir)
    elapsed = time.perf_counter() - t0

    size_mb = output_path.stat().st_size / (1024 * 1024) if output_path.is_file() else 0

    _done()
    _info(f"输出文件: {output_path}")
    _info(f"文件大小: {size_mb:.1f} MB")
    _info(f"合成耗时: {elapsed:.1f}s")

    return output_path


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI短剧制作自动流程 —— 一键视频生成流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py
  python main.py --input chapters/ch01.txt --series-title "第1集"
  python main.py --dry-run
  python main.py --max-workers 4
        """,
    )
    parser.add_argument(
        "--input", "-i", type=Path, default=DEFAULT_INPUT,
        help=f"输入小说文件路径 (默认: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--series-title", "-t", type=str, default="",
        help="剧集标题 (留空由 DeepSeek 自动生成)",
    )
    parser.add_argument(
        "--max-workers", "-w", type=int, default=6,
        help="资产下载并发线程数 (默认: 6)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式：跳过所有 API 调用，验证配置和代码完整性",
    )
    parser.add_argument(
        "--characters", "-c", type=Path, default=None,
        help="角色配置文件路径 (YAML/JSON)，用于角色视觉一致性和配音映射",
    )
    args = parser.parse_args()

    # ── 启动 ────────────────────────────────────────────────
    total_start = time.perf_counter()

    characters, char_config_path = _load_characters(args.characters)

    print()
    print("╔" + "═" * 48 + "╗")
    print("║" + "    📺  AI短剧制作自动流程".ljust(37) + "║")
    print("║" + f"    输入: {args.input.name}".ljust(37) + "║")
    mode = "DRY-RUN (不调用 API)" if args.dry_run else "正式运行"
    print("║" + f"    模式: {mode}".ljust(37) + "║")
    if characters:
        print("║" + f"    角色: {len(characters)} 人已加载".ljust(37) + "║")
    print("╚" + "═" * 48 + "╝")
    print()

    # ── Phase 1 ─────────────────────────────────────────────
    novel_text = phase_read_text(args.input)

    # ── Phase 2 ─────────────────────────────────────────────
    storyboard = phase_storyboard(
        novel_text,
        series_title=args.series_title,
        dry_run=args.dry_run,
        characters=characters,
    )

    # ── Phase 3 ─────────────────────────────────────────────
    asset_result = phase_assets(
        storyboard,
        dry_run=args.dry_run,
        max_workers=args.max_workers,
        characters=characters,
    )

    if not args.dry_run and characters and char_config_path:
        _update_character_refs(char_config_path, characters, asset_result.image_results, storyboard)

    # ── Phase 4: Seedance 图生视频 ─────────────────────────
    video_dir = phase_video_clips(
        storyboard,
        dry_run=args.dry_run,
    )

    # ── Phase 5: 视频合成 ─────────────────────────────────
    output_path = phase_video(
        storyboard,
        dry_run=args.dry_run,
        video_dir=video_dir,
    )

    # ── 汇总 ────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start

    print()
    print("╔" + "═" * 48 + "╗")
    print("║" + "    ✅  流水线执行完毕".ljust(44) + "║")
    print("║" + f"    总耗时: {total_elapsed:.1f}s".ljust(39) + "║")
    print("║" + f"    分镜数: {len(storyboard.scenes)}".ljust(39) + "║")
    if not args.dry_run:
        print("║" + f"    输出: {output_path.name}".ljust(39) + "║")
    print("╚" + "═" * 48 + "╝")
    print()


if __name__ == "__main__":
    main()
