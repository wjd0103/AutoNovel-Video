"""提示词生成器 —— 分镜描述 → AI 视频/图片生成 Prompt

Step 3 of the AI短剧制作自动流程:
  将每个镜头的画面内容描述转换为适合视频生成 API 的 Prompt
  - 前置拼接 全局视觉资产库（角色外貌/场景/风格）作为前缀
  - 中文场景描述 → 英文 Prompt（兼容主流视频生成 API）
  - 选择视觉风格
  - 输出最终 Prompt 供 API 调用
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from .storyboard_agent import ShotModel

if TYPE_CHECKING:
    from .asset_library import AssetLibrary

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 景别 → 镜头距离英文映射
# ═══════════════════════════════════════════════════════════════

SHOT_TYPE_TO_EN = {
    "远景": "wide shot, extreme long shot",
    "全景": "full shot, wide shot",
    "中景": "medium shot",
    "近景": "close-up shot",
    "特写": "extreme close-up shot",
}

# ═══════════════════════════════════════════════════════════════
# 镜头运动 → 英文描述
# ═══════════════════════════════════════════════════════════════

CAMERA_MOVEMENT_TO_EN = {
    "固定": "static camera",
    "推近": "zoom in",
    "拉远": "zoom out",
    "左移": "pan left",
    "右移": "pan right",
    "上摇": "tilt up",
    "下摇": "tilt down",
    "跟拍": "tracking shot, following the character",
}

# ═══════════════════════════════════════════════════════════════
# Prompt 模板
# ═════════════════════════════════════════════════════════════==

DEFAULT_STYLE = "anime style, consistent character design, cinematic lighting, high detail"

# 新模板：global_prefix 在最前，然后镜头/景别/场景/氛围
PROMPT_TEMPLATE = "{global_prefix}。{style}，{shot_type}，{camera}，{scene_content}，{atmosphere}"

ATMOSPHERE_MAP = {
    "紧张": "tense atmosphere, dramatic shadows",
    "悲伤": "melancholic mood, soft lighting",
    "欢乐": "warm atmosphere, bright lighting",
    "激昂": "dynamic composition, epic lighting",
    "悬疑": "mysterious atmosphere, low key lighting",
    "浪漫": "romantic mood, soft warm light, golden hour",
    "恐怖": "dark atmosphere, eerie shadows, horror mood",
    "平静": "peaceful atmosphere, soft natural light",
    "战斗": "dramatic action, dynamic motion, particle effects",
    "空灵": "ethereal atmosphere, dreamy lighting, misty",
}


# ═══════════════════════════════════════════════════════════════
# Prompt 生成器
# ═══════════════════════════════════════════════════════════════


class PromptGenerator:
    """将分镜描述转化为可用于 API 调用的 Prompt。

    增强功能：若传入 asset_library，自动在每个镜头 Prompt 最前面
    拼接该镜角色外貌 + 场景描述的全局资产前缀。

    用法::

        generator = PromptGenerator(visual_style="古风玄幻", asset_library=lib)
        shot_prompt = generator.generate(shot_model, atmosphere="战斗")
    """

    def __init__(
        self,
        visual_style: str = DEFAULT_STYLE,
        characters: Optional[list[dict]] = None,
        asset_library: Optional["AssetLibrary"] = None,
    ) -> None:
        self._style = visual_style
        self._characters = characters or []
        self._asset_library = asset_library

        if self._asset_library:
            logger.info("PromptGenerator 使用资产库  style=%s  characters=%d  scenes=%d",
                        visual_style[:30],
                        len(self._asset_library.characters),
                        len(self._asset_library.scenes))
        elif self._characters:
            char_desc = "; ".join(
                f"{ch.get('name', '?')}: {ch.get('appearance', '')}"
                for ch in self._characters
            )
            self._style = f"{visual_style}, character designs: {char_desc}"
            logger.info("PromptGenerator 初始化  style=%s  characters=%d", visual_style[:40], len(characters or []))

    def _build_global_prefix(self, shot: ShotModel) -> str:
        """根据资产库构建该镜头的全局视觉前缀

        包含：整体视觉风格 + 本镜出现角色的外貌描述 + 场景环境
        """
        if not self._asset_library:
            return self._style

        parts = [f"整体视觉风格：{self._asset_library.global_style}"]

        if shot.character_list:
            char_map = self._asset_library.build_character_map()
            char_descs = []
            for name in shot.character_list:
                desc = char_map.get(name, "")
                if desc:
                    char_descs.append(f"{name}：{desc}")
            if char_descs:
                parts.append("角色外貌：" + "；".join(char_descs))

        return "，".join(parts)

    def generate(
        self,
        shot: ShotModel,
        atmosphere: str = "",
    ) -> str:
        """为单个分镜生成 Prompt。

        Args:
            shot: ShotModel 分镜数据
            atmosphere: 氛围关键词

        Returns:
            最终 Prompt 字符串（全局前缀 + 镜头/景别/场景/氛围）
        """
        shot_type_en = SHOT_TYPE_TO_EN.get(shot.shot_type, "medium shot")
        camera_en = CAMERA_MOVEMENT_TO_EN.get(shot.camera_movement, "static camera")

        global_prefix = self._build_global_prefix(shot)

        scene_desc = shot.scene_content
        if shot.character_list:
            chars_desc = ", ".join(shot.character_list)
            scene_desc = f"{scene_desc}, featuring {chars_desc}"

        atmosphere_desc = ATMOSPHERE_MAP.get(atmosphere, "")

        prompt = PROMPT_TEMPLATE.format(
            global_prefix=global_prefix,
            style=self._style,
            shot_type=shot_type_en,
            camera=camera_en,
            scene_content=scene_desc,
            atmosphere=atmosphere_desc,
        ).strip(", ")

        while ",  " in prompt:
            prompt = prompt.replace(",  ", ", ")

        return prompt

    def generate_episode_plans(
        self,
        episode_storyboard,
        shot_atmospheres: Optional[dict[int, str]] = None,
    ):
        """为一集的所有分镜生成 Prompt 计划。"""
        from 核心.剧本.script_models import ShotVideoPrompt

        results = []
        for shot in episode_storyboard.shots:
            atmosphere = ""
            if shot_atmospheres:
                atmosphere = shot_atmospheres.get(shot.id, "")
            prompt = self.generate(shot, atmosphere)

            results.append(ShotVideoPrompt(
                episode_number=episode_storyboard.episode_number,
                shot_id=shot.id,
                image_prompt=prompt,
                duration=shot.duration,
                audio_text=shot.audio_content,
                voice_id=shot.voice_id,
            ))
        return results


def generate_shot_prompt(
    shot: ShotModel,
    visual_style: str = DEFAULT_STYLE,
    atmosphere: str = "",
    characters: Optional[list[dict]] = None,
    asset_library: Optional["AssetLibrary"] = None,
) -> str:
    """一键为单镜生成 Prompt。"""
    gen = PromptGenerator(visual_style=visual_style, characters=characters, asset_library=asset_library)
    return gen.generate(shot, atmosphere=atmosphere)
