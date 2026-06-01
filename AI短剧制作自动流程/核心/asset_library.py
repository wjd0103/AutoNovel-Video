"""全局视觉资产库 —— 提取故事核心角色/场景的结构化特征，供 Seedance Prompt 拼接

在前置步骤中，从 SeriesScript 中提取：
  - 每个核心角色的外貌、穿着、英文视觉关键词
  - 每个核心场景的视觉描述、英文视觉关键词
  - 全局视觉风格前缀

保存为 JSON 资产库文件，后续 PromptGenerator 自动将其作为前缀拼接到每个镜头的提示词。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .剧本.script_models import SeriesScript

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


class CharacterAsset:
    """单个角色的视觉资产"""

    def __init__(
        self,
        name: str,
        appearance: str,
        clothing: str = "",
        visual_keywords_en: str = "",
        voice_id: str = "narrator",
        reference_image_path: str = "",
    ):
        self.name = name
        self.appearance = appearance
        self.clothing = clothing
        self.visual_keywords_en = visual_keywords_en
        self.voice_id = voice_id
        self.reference_image_path = reference_image_path

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "appearance": self.appearance,
            "clothing": self.clothing,
            "visual_keywords_en": self.visual_keywords_en,
            "voice_id": self.voice_id,
            "reference_image_path": self.reference_image_path,
        }

    def build_prefix(self) -> str:
        """生成角色视觉前缀，用于拼入每个镜头 Prompt"""
        parts = [self.appearance]
        if self.clothing:
            parts.append(f"身穿{self.clothing}")
        return "，".join(parts)


class SceneAsset:
    """单个场景的视觉资产"""

    def __init__(self, name: str, description: str, visual_keywords_en: str = ""):
        self.name = name
        self.description = description
        self.visual_keywords_en = visual_keywords_en

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "visual_keywords_en": self.visual_keywords_en,
        }

    def build_prefix(self) -> str:
        return self.description


class AssetLibrary:
    """全局视觉资产库

    用法::
        library = AssetLibrary.from_series_script(script)
        prefix = library.build_global_prefix()
        # → 得到可直接拼入 Seedance Prompt 的中文前缀
    """

    def __init__(
        self,
        global_style: str = "",
        bgm_description: str = "",
        characters: Optional[list[CharacterAsset]] = None,
        scenes: Optional[list[SceneAsset]] = None,
    ):
        self.global_style = global_style
        self.bgm_description = bgm_description
        self.characters = characters or []
        self.scenes = scenes or []

    @classmethod
    def from_series_script(cls, script: SeriesScript) -> "AssetLibrary":
        """从 SeriesScript 提取并构建资产库"""
        chars = []
        for ch in script.settings.characters:
            # 从 appearance 拆出服饰关键词（逗号/句号后的部分视为服饰描述）
            appearance = ch.appearance
            clothing = _extract_clothing(appearance)
            # 构造英文视觉关键词（用于跨模型兼容）
            visual_en = _build_visual_keywords_en(ch)

            chars.append(CharacterAsset(
                name=ch.name,
                appearance=appearance,
                clothing=clothing,
                visual_keywords_en=visual_en,
                voice_id=ch.voice_id,
            ))

        scenes_list = []
        for sc in script.settings.important_scenes:
            scenes_list.append(SceneAsset(
                name=sc.name,
                description=sc.description,
                visual_keywords_en=sc.description[:60],
            ))

        return cls(
            global_style=script.settings.visual_style,
            bgm_description=script.settings.bgm_description,
            characters=chars,
            scenes=scenes_list,
        )

    def build_global_prefix(self) -> str:
        """构建完整的全局视觉前缀字符串

        这个字符串会被自动拼接到每个镜头的 Prompt 最前面。
        """
        parts = [f"整体视觉风格：{self.global_style}。"]

        if self.characters:
            parts.append("角色设定：")
            for ch in self.characters:
                prefix = ch.build_prefix()
                parts.append(f"  {ch.name}：{prefix}")

        if self.scenes:
            parts.append("重要场景：")
            for sc in self.scenes:
                parts.append(f"  {sc.name}：{sc.build_prefix()}")

        return "\n".join(parts)

    def build_global_style_line(self) -> str:
        """生成一行式全局风格描述，适合直接拼入 Prompt 开头"""
        return self.global_style

    def build_character_map(self) -> dict[str, str]:
        """{角色名: 外貌描述} 映射，用于 PromptGenerator 快速查找"""
        return {ch.name: ch.build_prefix() for ch in self.characters}

    def build_character_image_map(self) -> dict[str, str]:
        """{角色名: 参考图 base64 URL} 映射，用于 Seedance image_references"""
        result: dict[str, str] = {}
        for ch in self.characters:
            if ch.reference_image_path and Path(ch.reference_image_path).is_file():
                import base64
                img_path = Path(ch.reference_image_path)
                ext = img_path.suffix.lower()
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
                b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
                result[ch.name] = f"data:{mime};base64,{b64}"
        return result

    def update_reference_images(self, image_map: dict[str, Path]) -> None:
        """从肖像生成结果更新角色参考图路径。"""
        for ch in self.characters:
            if ch.name in image_map:
                ch.reference_image_path = str(image_map[ch.name])
                logger.info("角色 %s 参考图更新: %s", ch.name, image_map[ch.name].name)

    def to_dict(self) -> dict:
        return {
            "global_style": self.global_style,
            "bgm_description": self.bgm_description,
            "characters": [c.to_dict() for c in self.characters],
            "scenes": [s.to_dict() for s in self.scenes],
        }

    def save(self, path: Path) -> None:
        """保存资产库为 JSON 文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("资产库已保存: %s  (%d 角色, %d 场景)", path.name, len(self.characters), len(self.scenes))

    @classmethod
    def load(cls, path: Path) -> "AssetLibrary":
        """从 JSON 文件加载资产库"""
        data = json.loads(path.read_text(encoding="utf-8"))
        chars = [CharacterAsset(**c) for c in data.get("characters", [])]
        scenes_list = [SceneAsset(**s) for s in data.get("scenes", [])]
        return cls(
            global_style=data.get("global_style", ""),
            bgm_description=data.get("bgm_description", ""),
            characters=chars,
            scenes=scenes_list,
        )


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _extract_clothing(appearance: str) -> str:
    """从外貌描述中提取服饰信息"""
    keywords = ["穿", "着", "戴", "身", "披", "围"]
    for kw in keywords:
        idx = appearance.find(kw)
        if idx != -1:
            return appearance[idx:].split("，")[0].split("。")[0].split("；")[0]
    return ""


def _build_visual_keywords_en(char) -> str:
    """为角色生成英文视觉关键词"""
    name = char.name
    appearance = char.appearance
    gender = char.gender
    default_en = {
        "男": "male, ",
        "女": "female, ",
    }
    gender_prefix = default_en.get(gender, "")
    return f"{gender_prefix}{appearance[:40]}"


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def extract_asset_library(script: SeriesScript) -> AssetLibrary:
    """从 SeriesScript 提取全局视觉资产库。"""
    return AssetLibrary.from_series_script(script)


def build_shot_prompt_with_assets(
    shot,
    asset_library: AssetLibrary,
    shot_type_en: str = "medium shot",
    camera_en: str = "static camera",
    atmosphere: str = "",
) -> str:
    """使用资产库前缀构建单个镜头的完整 Prompt。"""
    from .prompt_generator import PROMPT_TEMPLATE, ATMOSPHERE_MAP

    # 查找本镜出现角色的外貌描述
    char_prefix = ""
    if shot.character_list:
        char_map = asset_library.build_character_map()
        descs = [char_map.get(name, "") for name in shot.character_list]
        descs = [d for d in descs if d]
        if descs:
            char_prefix = "角色外貌：" + "；".join(descs)

    # 构建场景内容（含角色外貌前缀）
    scene_desc = shot.scene_content
    if char_prefix:
        scene_desc = f"{char_prefix}。{scene_desc}"
    if shot.character_list:
        chars_desc = ", ".join(shot.character_list)
        scene_desc = f"{scene_desc}, featuring {chars_desc}"

    atmosphere_desc = ATMOSPHERE_MAP.get(atmosphere, "")

    prompt = PROMPT_TEMPLATE.format(
        style=asset_library.build_global_style_line(),
        shot_type=shot_type_en,
        camera=camera_en,
        scene_content=scene_desc,
        atmosphere=atmosphere_desc,
    ).strip(", ")

    while ",  " in prompt:
        prompt = prompt.replace(",  ", ", ")

    return prompt
