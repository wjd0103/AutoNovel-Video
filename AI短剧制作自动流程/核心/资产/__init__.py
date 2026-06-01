"""多模态资产生成 & 下载

包含:
  - CharacterPortraitGenerator: 调用生图 API 生成角色肖像（供 Seedance 参考图使用）
"""

from .image_generator import CharacterPortraitGenerator, generate_character_portraits

__all__ = ["CharacterPortraitGenerator", "generate_character_portraits"]
