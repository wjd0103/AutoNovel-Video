"""剧本持久化 —— 将剧本结构化数据保存为 JSON 和可读 Markdown
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Union

from .script_models import (
    OUTPUT_DIR,
    SCRIPT_DIR,
    EPISODE_DIR,
    FINAL_DIR,
    SeriesScript,
)
from ..storyboard_agent import EpisodeStoryboard

logger = logging.getLogger(__name__)


def save_series_script(script: SeriesScript) -> Path:
    """保存全剧设定 + 分集大纲为 JSON。

    Returns:
        json_path
    """
    safe_title = script.settings.title.replace("/", "_").replace(" ", "_")
    json_path = SCRIPT_DIR / f"{safe_title}_全剧剧本.json"

    json_path.write_text(
        script.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("全剧剧本已保存: %s", json_path.name)
    return json_path


def save_series_script_markdown(script: SeriesScript) -> Path:
    """保存全剧设定 + 分集大纲为可读 Markdown。"""
    safe_title = script.settings.title.replace("/", "_").replace(" ", "_")
    md_path = SCRIPT_DIR / f"{safe_title}_全剧剧本.md"

    lines = [
        f"# {script.settings.title} —— 全剧剧本大纲",
        "",
        "---",
        "## 全剧设定",
        "",
        f"- **类型**: {script.settings.genre}",
        f"- **视觉风格**: {script.settings.visual_style}",
        f"- **标签**: {'、'.join(script.settings.tags)}",
        f"- **背景音乐**: {script.settings.bgm_description}",
        "",
        "### 主要角色",
        "",
    ]
    for ch in script.settings.characters:
        lines.append(f"- **{ch.name}**（{ch.gender}）")
        lines.append(f"  - 外貌: {ch.appearance}")
        lines.append(f"  - 性格: {ch.personality}")
        lines.append(f"  - 配音: `{ch.voice_id}`（{ch.voice_name}）")
        lines.append("")

    lines.append("### 重要场景")
    lines.append("")
    for sc in script.settings.important_scenes:
        lines.append(f"- **{sc.name}**: {sc.description}")
    lines.append("")

    lines.append("---")
    lines.append("## 分集大纲")
    lines.append("")

    for ep in script.episodes:
        lines.append(f"### 第{ep.episode_number}集 · {ep.title}")
        lines.append("")
        lines.append(f"- **预估时长**: {ep.estimated_duration}")
        if ep.chapter_range:
            lines.append(f"- **原文章节**: {ep.chapter_range}")
        lines.append(f"- **大纲**: {ep.outline}")
        lines.append(f"- **结尾钩子**: {ep.cliffhanger}")
        lines.append("")
        lines.append("---")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("全剧剧本 Markdown 已保存: %s", md_path.name)
    return md_path


def save_episode_storyboard(storyboard: EpisodeStoryboard) -> tuple[Path, Path]:
    """保存一集的分镜为 JSON 和 Markdown。

    Returns:
        (json_path, md_path)
    """
    ep_dir = EPISODE_DIR / f"第{storyboard.episode_number:02d}集"
    ep_dir.mkdir(parents=True, exist_ok=True)

    json_path = ep_dir / "分镜.json"
    md_path = ep_dir / "分镜.md"

    json_path.write_text(
        storyboard.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        f"# 第{storyboard.episode_number}集 · {storyboard.episode_title} —— 分镜表",
        "",
        f"**总镜数**: {len(storyboard.shots)}",
        "",
        "---",
        "",
    ]
    for shot in storyboard.shots:
        chars = "、".join(shot.character_list) if shot.character_list else "（无）"
        lines.append(f"## 第{shot.id}镜")
        lines.append("")
        lines.append(f"- **镜头**: `{shot.camera_movement}`")
        lines.append(f"- **景别**: `{shot.shot_type}`")
        lines.append(f"- **时长**: {shot.duration}秒")
        lines.append(f"- **角色**: {chars}")
        lines.append(f"- **配音**: `{shot.voice_id}`")
        lines.append(f"- **画面**: {shot.scene_content}")
        lines.append(f"- **音频**: {shot.audio_content}")
        if shot.notes:
            lines.append(f"- **备注**: {shot.notes}")
        lines.append("")
        lines.append("---")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    logger.info("第%d集分镜已保存  json=%s  md=%s", storyboard.episode_number, json_path.name, md_path.name)
    return json_path, md_path
