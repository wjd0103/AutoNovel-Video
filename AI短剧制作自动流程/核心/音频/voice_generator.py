"""TTS 配音生成器 —— 将分镜音频文本转为语音文件

支持 edge-tts（免费，已安装）和 OpenAI TTS。
根据分镜的 voice_id 自动匹配音色。
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from 配置 import config as cfg

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 音色映射表
# ═══════════════════════════════════════════════════════════════

# edge-tts 中文音色
EDGE_CHINESE_VOICES: dict[str, str] = {
    "female_lead": "zh-CN-XiaoxiaoNeural",    # 女声，温柔
    "male_lead": "zh-CN-YunxiNeural",          # 男声，沉稳
    "narrator": "zh-CN-XiaoxiaoNeural",        # 旁白，默认女声
    "supporting_female": "zh-CN-XiaoyiNeural", # 女配，活泼
    "supporting_male": "zh-CN-YunjianNeural",  # 男配，磁性
    "default": "zh-CN-XiaoxiaoNeural",
}

# OpenAI TTS 音色
OPENAI_VOICES: dict[str, str] = {
    "female_lead": "nova",
    "male_lead": "onyx",
    "narrator": "alloy",
    "supporting_female": "shimmer",
    "supporting_male": "echo",
    "default": "alloy",
}


class VoiceGenerator:
    """TTS 配音生成器。

    用法::

        gen = VoiceGenerator(tts_type="edge-tts")
        path = gen.generate("苏晚：你给了我，你怎么办？", voice_id="female_lead")
        # → 输出/音频/batch_01_shot_02.wav
    """

    def __init__(self, tts_type: str = "", voice_speed: float = 1.0):
        self._type = (tts_type or cfg.TTS_API_TYPE).lower()
        self._speed = voice_speed or cfg.TTS_SPEED
        self._output_dir = Path(cfg.PROJECT_ROOT) / "输出" / "音频"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, text: str, voice_id: str = "narrator", filename: str = "") -> Optional[Path]:
        """将文本转为语音文件。

        Args:
            text: 配音文本
            voice_id: 配音角色标识
            filename: 输出文件名（不含路径），空则自动生成

        Returns:
            生成的音频文件路径，失败返回 None
        """
        if not text.strip():
            logger.debug("空文本，跳过 TTS")
            return None

        if not filename:
            import hashlib
            h = hashlib.md5(text.encode()).hexdigest()[:8]
            filename = f"voice_{h}.wav"

        output_path = self._output_dir / filename

        if output_path.is_file():
            logger.debug("TTS 缓存命中: %s", filename)
            return output_path

        if self._type == "edge-tts":
            return self._generate_edge(text, voice_id, output_path)
        elif self._type == "openai":
            return self._generate_openai(text, voice_id, output_path)
        else:
            logger.warning("不支持的 TTS 类型: %s", self._type)
            return None

    # ── edge-tts ────────────────────────────────────────────

    def _generate_edge(self, text: str, voice_id: str, output_path: Path) -> Optional[Path]:
        try:
            import edge_tts

            voice_name = EDGE_CHINESE_VOICES.get(voice_id, EDGE_CHINESE_VOICES["default"])
            communicate = edge_tts.Communicate(text, voice_name)
            asyncio.run(communicate.save(str(output_path)))
            size_kb = output_path.stat().st_size / 1024
            logger.info("TTS [edge-tts] voice=%s  %s  (%.0f KB)", voice_name, output_path.name, size_kb)
            return output_path

        except Exception as e:
            logger.error("edge-tts 失败 (%s): %s", voice_id, e)
            return None

    # ── OpenAI TTS ──────────────────────────────────────────

    def _generate_openai(self, text: str, voice_id: str, output_path: Path) -> Optional[Path]:
        try:
            from openai import OpenAI

            voice_name = OPENAI_VOICES.get(voice_id, OPENAI_VOICES["default"])
            client = OpenAI(api_key=cfg.LLM_API_KEY, base_url=cfg.LLM_BASE_URL)
            response = client.audio.speech.create(
                model="tts-1",
                voice=voice_name,
                input=text,
                speed=self._speed,
            )
            response.stream_to_file(str(output_path))
            size_kb = output_path.stat().st_size / 1024
            logger.info("TTS [openai] voice=%s  %s  (%.0f KB)", voice_name, output_path.name, size_kb)
            return output_path

        except Exception as e:
            logger.error("OpenAI TTS 失败 (%s): %s", voice_id, e)
            return None


# ═══════════════════════════════════════════════════════════════
# 批量生成 —— 按 Batch 拼接多镜配音
# ═══════════════════════════════════════════════════════════════


def generate_batch_voice(
    shots: list[dict],
    batch_id: int,
    episode_number: int,
    tts_type: str = "",
) -> Optional[Path]:
    """为一组分镜生成拼接后的配音音频。

    将同一 Batch 内多个分镜的 audio_content 分别 TTS 后，
    按分镜顺序拼接为一条完整的配音音频。

    Args:
        shots: 分镜列表，每个元素需包含 id, audio_content, voice_id, duration
        batch_id: Batch 编号
        episode_number: 集号

    Returns:
        拼接后的音频路径，失败返回 None
    """
    gen = VoiceGenerator(tts_type=tts_type)

    temp_dir = Path(cfg.PROJECT_ROOT) / "输出" / "音频" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    audio_segments: list[tuple[Path, float]] = []

    for i, shot in enumerate(shots):
        text = shot.get("audio_content", "").strip()
        if not text:
            continue

        voice_id = shot.get("voice_id", "narrator")
        filename = f"ep{episode_number:02d}_batch{batch_id:02d}_shot{shot['id']:02d}.wav"
        result = gen.generate(text, voice_id=voice_id, filename=filename)

        if result and result.is_file():
            audio_segments.append((result, shot.get("duration", 4.0)))
            logger.info("  镜%02d TTS: %s", shot["id"], filename)

    if not audio_segments:
        logger.warning("Batch%d 无有效配音文本", batch_id)
        return None

    # ── 拼接 ──
    from moviepy import AudioFileClip, concatenate_audioclips

    clips = []
    for audio_path, _ in audio_segments:
        try:
            clip = AudioFileClip(str(audio_path))
            clips.append(clip)
        except Exception as e:
            logger.warning("音频加载失败: %s (%s)", audio_path.name, e)

    if not clips:
        return None

    final_audio = concatenate_audioclips(clips)

    output_path = Path(cfg.PROJECT_ROOT) / "输出" / "音频" / f"ep{episode_number:02d}_batch{batch_id:02d}_voice.wav"
    final_audio.write_audiofile(str(output_path), logger=None)
    final_audio.close()
    for c in clips:
        c.close()

    size_kb = output_path.stat().st_size / 1024
    logger.info("Batch%d 配音拼接完成: %s  (%.0f KB, %d 段)", batch_id, output_path.name, size_kb, len(clips))

    return output_path


# ── 便捷函数 ──


def generate_voice(text: str, voice_id: str = "narrator") -> Optional[Path]:
    """一键单条 TTS。"""
    gen = VoiceGenerator()
    return gen.generate(text, voice_id=voice_id)
