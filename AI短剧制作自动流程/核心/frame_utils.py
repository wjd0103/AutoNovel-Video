"""帧工具 + 镜头批处理器

功能:
  1. ShotBatcher — 将连续分镜按总时长 ≤15s 分组
  2. extract_and_save_last_frame — 提取视频最后一帧保存为图片
  3. build_batch_prompt — 将一组镜头的描述拼接为一条 Prompt
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# ShotBatcher
# ═══════════════════════════════════════════════════════════════

VALID_DURS = [4, 5, 6, 8, 10, 12, 15]


def round_duration(requested: float) -> int:
    """圆整到 Seedance 支持的固定时长"""
    return min(VALID_DURS, key=lambda x: abs(x - requested))


class ShotBatcher:
    """将分镜列表按总时长 ≤max_duration 分组。

    用法::

        batcher = ShotBatcher(max_duration=15)
        batches = batcher.batch(shots)  # shots = [(id, duration, desc, chars), ...]
        # → [BatchInfo(batch_id=1, shots=[1,2,3], total_dur=14, ...), ...]
    """

    def __init__(self, max_duration: int = 15):
        self.max_duration = max_duration

    def batch(self, shots: list[dict]) -> list[dict]:
        """将镜头列表分组。

        Args:
            shots: 每个元素为 {shot_id, duration, scene_content, camera_movement,
                   shot_type, character_list, audio_content, ...}

        Returns:
            [{
              "batch_id": 1,
              "shot_ids": [1, 2],
              "shot_count": 2,
              "total_duration": 9.0,
              "seedance_duration": 8,  # 圆整后的 API 时长
              "prompt": "...合并后的描述...",
              "characters": ["苏晚", "陆承安"],  # 合并角色列表
              "shots": [shot_dict, ...]
            }, ...]
        """
        batches: list[dict] = []
        current_group: list[dict] = []
        current_dur = 0.0

        for shot in shots:
            dur = shot.get("duration", 4.0)
            if current_dur + dur > self.max_duration and current_group:
                # 当前组塞不下了，结算
                batches.append(self._finalize(current_group))
                current_group = []
                current_dur = 0.0
            current_group.append(shot)
            current_dur += dur

        if current_group:
            batches.append(self._finalize(current_group))

        # 记录统计
        total_shot_count = sum(b["shot_count"] for b in batches)
        logger.info(
            "ShotBatcher: %d 镜头 → %d 批  (每批 ≤%ds, 平均每批 %.1f 镜)",
            total_shot_count, len(batches), self.max_duration,
            total_shot_count / max(len(batches), 1),
        )
        return batches

    def _finalize(self, group: list[dict]) -> dict:
        total_dur = sum(s.get("duration", 4.0) for s in group)
        seedance_dur = round_duration(total_dur)

        # 合并所有角色
        all_chars: list[str] = []
        for s in group:
            for c in s.get("character_list", []):
                if c not in all_chars:
                    all_chars.append(c)

        # 构建合并描述
        prompt = self._build_prompt(group)

        return {
            "batch_id": 0,  # 调用方重新编号
            "shot_ids": [s["id"] for s in group],
            "shot_count": len(group),
            "total_duration": total_dur,
            "seedance_duration": seedance_dur,
            "prompt": prompt,
            "characters": all_chars,
            "shots": group,
        }

    @staticmethod
    def _build_prompt(group: list[dict]) -> str:
        """将一组镜头的描述合并为一条连续叙事 Prompt。"""
        parts = []
        for i, s in enumerate(group):
            camera = s.get("camera_movement", "固定")
            shot_type = s.get("shot_type", "中景")
            scene = s.get("scene_content", "")
            audio = s.get("audio_content", "")
            notes = s.get("notes", "")

            seg = f"【第{i+1}镜-{shot_type}-{camera}】{scene}"
            if audio:
                seg += f"。音频：{audio}"
            if notes:
                seg += f"。备注：{notes}"
            parts.append(seg)

        prompt = "连续场景：\n" + "\n".join(parts)
        prompt += "\n整体风格：温暖细腻电影感画面，柔和自然光，自然流畅的镜头转接。"
        return prompt


# ═══════════════════════════════════════════════════════════════
# 视频帧提取
# ═══════════════════════════════════════════════════════════════


def extract_and_save_last_frame(
    video_path: Path,
    output_path: Path,
    method: str = "moviepy",
) -> Optional[Path]:
    """提取视频最后一帧并保存为 PNG 图片。

    Args:
        video_path: 输入视频路径
        output_path: 输出图片路径 (后缀应为 .png)
        method: "moviepy" 或 "ffmpeg"

    Returns:
        保存成功的图片路径, 失败返回 None
    """
    if not video_path.is_file():
        logger.warning("视频文件不存在: %s", video_path)
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if method == "ffmpeg":
        return _extract_via_ffmpeg(video_path, output_path)
    else:
        return _extract_via_moviepy(video_path, output_path)


def _extract_via_moviepy(video_path: Path, output_path: Path) -> Optional[Path]:
    try:
        from moviepy import VideoFileClip

        with VideoFileClip(str(video_path)) as clip:
            last_frame = clip.get_frame(clip.duration - 0.04)
            from moviepy import ImageClip

            img_clip = ImageClip(last_frame, duration=0.1)
            img_clip.save_frame(str(output_path))
            logger.info("帧提取 (moviepy): %s  →  %s", video_path.name, output_path.name)
            return output_path
    except Exception as e:
        logger.warning("moviepy 帧提取失败: %s, 尝试 ffmpeg...", e)
        return _extract_via_ffmpeg(video_path, output_path)


def _extract_via_ffmpeg(video_path: Path, output_path: Path) -> Optional[Path]:
    try:
        cmd = [
            "ffmpeg", "-y",
            "-sseof", "-0.1",  # 从末尾 0.1 秒处
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=30)
        if output_path.is_file():
            logger.info("帧提取 (ffmpeg): %s  →  %s", video_path.name, output_path.name)
            return output_path
        logger.warning("ffmpeg 未生成文件: %s", output_path)
        return None
    except Exception as e:
        logger.error("ffmpeg 帧提取失败: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════
# Batch 信息持久化
# ═══════════════════════════════════════════════════════════════

def save_batch_manifest(batches: list[dict], output_path: Path) -> None:
    """将 batch 分组信息保存为 JSON。"""
    import json

    manifest = []
    for b in batches:
        manifest.append({
            "batch_id": b["batch_id"],
            "shot_ids": b["shot_ids"],
            "shot_count": b["shot_count"],
            "total_duration": b["total_duration"],
            "seedance_duration": b["seedance_duration"],
            "characters": b["characters"],
            "prompt_preview": b["prompt"][:100] + "...",
        })
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Batch manifest 已保存: %s  (%d batches)", output_path.name, len(manifest))
