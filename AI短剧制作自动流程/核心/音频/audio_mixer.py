"""音频合成器 —— 将配音轨合成到视频中

功能:
  - 将配音音频混入无声视频
  - 支持配音+视频时长对齐（循环/延长至视频长度）
  - 输出最终 mp4
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from moviepy import AudioFileClip, VideoFileClip, CompositeAudioClip

logger = logging.getLogger(__name__)


def _set_volume(clip, vol: float):
    """兼容不同 moviepy 版本的音量设置。"""
    try:
        return clip.multiply_volume(vol)
    except AttributeError:
        try:
            return clip.with_volume_scaled(vol)
        except AttributeError:
            return clip


def mix_voice_to_video(
    video_path: Path,
    audio_path: Optional[Path],
    output_path: Path,
    volume: float = 1.0,
) -> Optional[Path]:
    """将配音音频合成到视频中。

    Args:
        video_path: 无声视频路径
        audio_path: 配音音频路径（None 则直接复制视频）
        output_path: 输出视频路径
        volume: 配音音量比例

    Returns:
        输出路径，失败返回 None
    """
    if not video_path.is_file():
        logger.error("视频文件不存在: %s", video_path)
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        video = VideoFileClip(str(video_path))

        if audio_path and audio_path.is_file():
            audio = AudioFileClip(str(audio_path))

            # 若音频短于视频，末尾静音补齐
            if audio.duration < video.duration:
                silence_dur = video.duration - audio.duration
                silence = AudioFileClip(str(audio_path)).with_duration(silence_dur)
                silence = _set_volume(silence, 0)
                final_audio = CompositeAudioClip([audio, silence.with_start(audio.duration)])
            else:
                final_audio = audio.with_duration(video.duration)

            final_audio = _set_volume(final_audio, volume)
            video = video.with_audio(final_audio)

        video.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            fps=24,
            logger=None,
        )

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info("视频+配音合成完成: %s  (%.1f MB)", output_path.name, size_mb)
        return output_path

    except Exception as e:
        logger.error("视频+配音合成失败: %s", e)
        return None

    finally:
        try:
            video.close()
        except Exception:
            pass
