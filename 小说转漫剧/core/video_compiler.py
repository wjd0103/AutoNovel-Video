"""视频合成引擎 —— 分镜图片 + 配音 + 字幕 → 完整漫剧视频

使用 moviepy 将 output/images/ 和 output/audio/ 中的资产合成为一条
带运镜动效、中文字幕和配音的最终 mp4 文件。
"""

from __future__ import annotations

import logging
import os
import platform
import time
from pathlib import Path
from typing import Optional

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    concatenate_videoclips,
)

from config import config as cfg
from core.storyboard_agent import CameraMovement, SceneModel, StoryboardModel

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = PROJECT_ROOT / "output" / "images"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
FINAL_DIR = PROJECT_ROOT / "output" / "final"
FINAL_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_OUTPUT_NAME = "final_manju_video.mp4"

# ═══════════════════════════════════════════════════════════════
# 字体检测
# ═══════════════════════════════════════════════════════════════

_FONT_CANDIDATES: list[str] = []

_system = platform.system()
if _system == "Darwin":
    _FONT_CANDIDATES = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
elif _system == "Windows":
    _FONT_CANDIDATES = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ]
else:
    _FONT_CANDIDATES = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]


def _detect_chinese_font() -> Optional[str]:
    custom = os.environ.get("SUBTITLE_FONT", "").strip()
    if custom and Path(custom).is_file():
        return custom

    for fp in _FONT_CANDIDATES:
        if Path(fp).is_file():
            return fp

    return None


_FONT_PATH: Optional[str] = _detect_chinese_font()

# ═══════════════════════════════════════════════════════════════
# 运镜参数映射
# ═══════════════════════════════════════════════════════════════

_BASE_SCALE = 1.08  # 基础 overscan（为运镜留出 8% 的裁切空间）


def _movement_params(movement: CameraMovement) -> dict:
    """根据 camera_movement 返回 (zoom_start, zoom_end, pan_x_start, pan_y_start, pan_x_end, pan_y_end)

    pan 值范围 0.0-1.0，表示在 overscan margin 中的位置比例（0.5 = 居中）。
    """
    zs, ze = _BASE_SCALE, _BASE_SCALE * 1.05  # 默认轻微放大

    px_s, py_s = 0.5, 0.5
    px_e, py_e = 0.5, 0.5

    if movement == "static":
        zs, ze = _BASE_SCALE, _BASE_SCALE * 1.04
    elif movement == "zoom_in":
        zs, ze = _BASE_SCALE, _BASE_SCALE * 1.12
    elif movement == "zoom_out":
        zs, ze = _BASE_SCALE * 1.12, _BASE_SCALE
    elif movement == "pan_left":
        zs, ze = _BASE_SCALE, _BASE_SCALE * 1.05
        px_s, px_e = 0.75, 0.25
    elif movement == "pan_right":
        zs, ze = _BASE_SCALE, _BASE_SCALE * 1.05
        px_s, px_e = 0.25, 0.75
    elif movement == "tilt_up":
        zs, ze = _BASE_SCALE, _BASE_SCALE * 1.05
        py_s, py_e = 0.75, 0.25
    elif movement == "tilt_down":
        zs, ze = _BASE_SCALE, _BASE_SCALE * 1.05
        py_s, py_e = 0.25, 0.75

    return {
        "zoom_start": zs,
        "zoom_end": ze,
        "pan_x_start": px_s,
        "pan_y_start": py_s,
        "pan_x_end": px_e,
        "pan_y_end": py_e,
    }


# ═══════════════════════════════════════════════════════════════
# 字幕构建
# ═══════════════════════════════════════════════════════════════

def _build_subtitle(
    text: str,
    duration: float,
    font_path: str,
    frame_w: int,
    frame_h: int,
    font_size: int = 42,
    stroke_width: int = 2,
) -> TextClip:
    """创建中文字幕 TextClip，底部居中，带黑色描边。"""

    shadow_offset = 2
    shadow_clip = TextClip(
        text=text,
        font=font_path,
        font_size=font_size,
        color="black",
        text_align="center",
        method="label",
    ).with_duration(duration)

    main_clip = TextClip(
        text=text,
        font=font_path,
        font_size=font_size,
        color="white",
        stroke_color="black",
        stroke_width=stroke_width,
        text_align="center",
        method="label",
    ).with_duration(duration)

    subtitle_h = max(main_clip.h, shadow_clip.h) + 4
    subtitle_w = max(main_clip.w, shadow_clip.w)

    y_pos = frame_h - subtitle_h - 60

    shadow = shadow_clip.with_position(("center", y_pos + shadow_offset))
    main = main_clip.with_position(("center", y_pos))

    bg = ColorClip(size=(frame_w, frame_h), color=(0, 0, 0, 0)).with_duration(duration)
    comp = CompositeVideoClip([bg, shadow, main], size=(frame_w, frame_h))
    return comp


# ═══════════════════════════════════════════════════════════════
# 单场景片段构建
# ═══════════════════════════════════════════════════════════════

def _build_scene_clip(
    scene: SceneModel,
    image_dir: Path,
    audio_dir: Path,
    font_path: Optional[str],
    output_width: int,
    output_height: int,
    fps: int,
) -> CompositeVideoClip:
    """为单个分镜构建带运镜、字幕、配音的视频片段。"""

    W, H = output_width, output_height
    scene_id = scene.id

    img_path = image_dir / f"scene_{scene_id:02d}.png"
    if not img_path.is_file():
        raise FileNotFoundError(f"图片缺失: {img_path}")

    aud_path = audio_dir / f"scene_{scene_id:02d}.mp3"

    # ── 1. 音频 → 确定时长 ─────────────────────────────────
    audio_clip: Optional[AudioFileClip] = None
    if aud_path.is_file():
        try:
            audio_clip = AudioFileClip(str(aud_path))
        except Exception:
            logger.warning("音频加载失败 scene_%02d，使用默认时长", scene_id)

    clip_duration = audio_clip.duration if audio_clip else 3.0
    logger.debug("scene_%02d  duration=%.2fs  has_audio=%s", scene_id, clip_duration, audio_clip is not None)

    # ── 2. 图片 + 运镜动效 ──────────────────────────────────
    img_clip = ImageClip(str(img_path)).with_duration(clip_duration)

    params = _movement_params(scene.camera_movement)
    zs, ze = params["zoom_start"], params["zoom_end"]
    px_s, px_e = params["pan_x_start"], params["pan_x_end"]
    py_s, py_e = params["pan_y_start"], params["pan_y_end"]

    big_w, big_h = int(W * max(zs, ze)), int(H * max(zs, ze))
    img_scaled = img_clip.resized(new_size=(big_w, big_h))

    def _zoom_scale(t: float) -> float:
        progress = min(t / clip_duration, 1.0) if clip_duration > 0 else 1.0
        return zs + (ze - zs) * progress

    img_zoomed = img_scaled.resized(_zoom_scale)

    margin_x = max(big_w - W, 0)
    margin_y = max(big_h - H, 0)

    def _get_position(t: float) -> tuple[int, int]:
        progress = min(t / clip_duration, 1.0) if clip_duration > 0 else 1.0
        s = _zoom_scale(t)
        cw = int(W * s)
        ch = int(H * s)
        cx = (W - cw) // 2
        cy = (H - ch) // 2
        pan_x = margin_x * (px_s + (px_e - px_s) * progress - 0.5)
        pan_y = margin_y * (py_s + (py_e - py_s) * progress - 0.5)
        return (int(cx + pan_x), int(cy + pan_y))

    img_positioned = img_zoomed.with_position(_get_position)

    # ── 3. 构建合成层 ──────────────────────────────────────
    layers: list = [img_positioned]

    # 字幕
    if scene.dialogue.strip() and font_path:
        sub = _build_subtitle(
            scene.dialogue,
            clip_duration,
            font_path,
            W,
            H,
        )
        layers.append(sub)

    scene_clip = CompositeVideoClip(layers, size=(W, H))

    if audio_clip:
        scene_clip = scene_clip.with_audio(audio_clip)

    return scene_clip


def _build_seedance_scene_clip(
    scene: SceneModel,
    video_dir: Path,
    audio_dir: Path,
    font_path: Optional[str],
    output_width: int,
    output_height: int,
    fps: int,
) -> CompositeVideoClip:
    """为单个分镜构建基于 Seedance 视频片段的合成层。

    与 _build_scene_clip 不同：画面来自 Seedance 生成的 .mp4 片段（已有动效），
    不再叠加 zoom/pan 滤镜。只叠加字幕 + 配音。
    """

    from moviepy import VideoFileClip

    W, H = output_width, output_height
    scene_id = scene.id

    vid_path = video_dir / f"scene_{scene_id:02d}.mp4"
    if not vid_path.is_file():
        raise FileNotFoundError(f"视频片段缺失: {vid_path}")

    aud_path = audio_dir / f"scene_{scene_id:02d}.mp3"

    # ── 1. 视频片段 ────────────────────────────────────────
    try:
        video_clip = VideoFileClip(str(vid_path))
    except Exception:
        logger.warning("视频片段加载失败 scene_%02d，跳过", scene_id)
        raise

    clip_duration = video_clip.duration
    video_clip = video_clip.resized(new_size=(W, H))

    logger.debug("scene_%02d  seedance_dur=%.2fs", scene_id, clip_duration)

    # ── 2. 音频 → 覆盖/附加 ──────────────────────────────────
    audio_clip: Optional[AudioFileClip] = None
    if aud_path.is_file():
        try:
            audio_clip = AudioFileClip(str(aud_path))
        except Exception:
            logger.warning("音频加载失败 scene_%02d", scene_id)

    # ── 3. 字幕 ─────────────────────────────────────────────
    layers: list = [video_clip]

    if scene.dialogue.strip() and font_path:
        sub = _build_subtitle(
            scene.dialogue,
            clip_duration,
            font_path,
            W,
            H,
        )
        layers.append(sub)

    scene_clip = CompositeVideoClip(layers, size=(W, H))

    # ── 4. 音频处理 ────────────────────────────────────────
    if audio_clip:
        if audio_clip.duration > clip_duration:
            audio_clip = audio_clip.subclipped(0, clip_duration)
        elif audio_clip.duration < clip_duration:
            from moviepy import AudioClip
            padding = AudioClip(
                lambda t: 0,
                duration=clip_duration - audio_clip.duration,
                fps=audio_clip.fps,
            )
            audio_clip = concatenate_audioclips([audio_clip, padding])

        scene_clip = scene_clip.with_audio(audio_clip)

    return scene_clip


# ═══════════════════════════════════════════════════════════════
# 视频编译器（主类）
# ═══════════════════════════════════════════════════════════════


class VideoCompiler:
    """将 StoryboardModel + 本地资产合成为漫剧视频。

    用法::

        compiler = VideoCompiler()
        output_path = compiler.compile(storyboard)
        print(f"视频已生成: {output_path}")
    """

    def __init__(
        self,
        output_width: Optional[int] = None,
        output_height: Optional[int] = None,
        fps: Optional[int] = None,
        video_codec: Optional[str] = None,
        audio_codec: Optional[str] = None,
        audio_bitrate: Optional[str] = None,
        font_path: Optional[str] = None,
    ) -> None:
        self._w = output_width or cfg.OUTPUT.width
        self._h = output_height or cfg.OUTPUT.height
        self._fps = fps or cfg.OUTPUT.fps
        self._vcodec = video_codec or cfg.OUTPUT.video_codec
        self._acodec = audio_codec or cfg.OUTPUT.audio_codec
        self._abitrate = audio_bitrate or cfg.OUTPUT.audio_bitrate
        self._font = font_path or _FONT_PATH

        if self._font is None:
            logger.warning(
                "未找到中文字体文件，字幕将无法正常显示！"
                " 请设置环境变量 SUBTITLE_FONT 指向一个中文字体文件"
            )
        else:
            logger.info("使用字体: %s", self._font)

        logger.info(
            "VideoCompiler 初始化  %dx%d@%dfps  codec=%s",
            self._w, self._h, self._fps, self._vcodec,
        )

    # ── 主入口 ──────────────────────────────────────────────

    def compile(
        self,
        storyboard: StoryboardModel,
        output_path: Optional[str] = None,
        image_dir: Optional[Path] = None,
        audio_dir: Optional[Path] = None,
        video_dir: Optional[Path] = None,
    ) -> Path:
        """完整编译流程：分镜 → 片段 → 拼接 → 导出。

        Args:
            storyboard: StoryboardModel 分镜数据
            output_path: 输出路径（默认 output/final/final_manju_video.mp4）
            image_dir: 图片目录（默认 output/images/，video_dir 为 None 时生效）
            audio_dir: 音频目录（默认 output/audio/）
            video_dir: Seedance 视频片段目录（提供时使用 .mp4 替代 .png 作为画面源）

        Returns:
            输出文件的 Path
        """
        t_start = time.perf_counter()
        scenes = storyboard.scenes
        if not scenes:
            raise ValueError("分镜列表为空，无法合成")

        img_dir = image_dir or IMAGE_DIR
        aud_dir = audio_dir or AUDIO_DIR
        use_seedance = video_dir is not None

        logger.info("=" * 60)
        logger.info(
            "开始视频合成  title=%s  scenes=%d  %dx%d@%d  mode=%s",
            storyboard.series_title, len(scenes), self._w, self._h, self._fps,
            "seedance" if use_seedance else "image+zoom",
        )

        scene_clips: list = []
        for i, scene in enumerate(scenes):
            t0 = time.perf_counter()
            try:
                if use_seedance:
                    clip = _build_seedance_scene_clip(
                        scene, video_dir, aud_dir,
                        self._font, self._w, self._h, self._fps,
                    )
                else:
                    clip = _build_scene_clip(
                        scene, img_dir, aud_dir,
                        self._font, self._w, self._h, self._fps,
                    )
                scene_clips.append(clip)
                elapsed = time.perf_counter() - t0
                logger.info(
                    "  [%2d/%2d] ✅ scene_%02d  %.2fs  \"%s\"",
                    i + 1, len(scenes), scene.id, elapsed,
                    scene.dialogue[:25] + "…" if len(scene.dialogue) > 25 else scene.dialogue,
                )
            except FileNotFoundError:
                logger.warning(
                    "  [%2d/%2d] ⚠ scene_%02d  跳过（资源缺失）",
                    i + 1, len(scenes), scene.id,
                )
            except Exception:
                logger.exception(
                    "  [%2d/%2d] ❌ scene_%02d  构建失败",
                    i + 1, len(scenes), scene.id,
                )

        if not scene_clips:
            raise RuntimeError("没有成功构建任何场景片段，合成中止")

        # ── 线性拼接 ────────────────────────────────────────
        logger.info("正在拼接 %d 个片段…", len(scene_clips))
        t_concat = time.perf_counter()
        final_clip = concatenate_videoclips(
            scene_clips,
            method="compose",
        )
        concat_elapsed = time.perf_counter() - t_concat
        total_dur = final_clip.duration
        logger.info("拼接完成  总时长 %.1fs  耗时 %.1fs", total_dur, concat_elapsed)

        # ── 导出 ────────────────────────────────────────────
        out = Path(output_path) if output_path else (FINAL_DIR / DEFAULT_OUTPUT_NAME)
        logger.info("正在导出视频 → %s", out)

        t_export = time.perf_counter()
        final_clip.write_videofile(
            str(out),
            fps=self._fps,
            codec=self._vcodec,
            audio_codec=self._acodec,
            audio_bitrate=self._abitrate,
            threads=4,
            logger=None,
        )
        export_elapsed = time.perf_counter() - t_export

        # ── 清理 ────────────────────────────────────────────
        final_clip.close()
        for c in scene_clips:
            try:
                c.close()
            except Exception:
                pass

        total_elapsed = time.perf_counter() - t_start
        size_mb = out.stat().st_size / (1024 * 1024) if out.is_file() else 0

        logger.info("=" * 60)
        logger.info(
            "视频导出完成  path=%s  size=%.1fMB  duration=%.1fs  总耗时=%.1fs",
            out, size_mb, total_dur, total_elapsed,
        )
        return out


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def compile_video(
    storyboard: StoryboardModel,
    output_path: Optional[str] = None,
) -> Path:
    """一行调用：分镜脚本 → 最终视频。

    Args:
        storyboard: StoryboardModel 分镜数据（需先生成图片和音频资产）
        output_path: 输出路径
    """
    compiler = VideoCompiler()
    return compiler.compile(storyboard, output_path=output_path)
