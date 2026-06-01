"""角色肖像生成器 —— 调用豆包 Dolphin/Seedream API 生成角色参考图

根据资产库中的角色外貌描述，为每个角色生成一张标准肖像图，
保存到 输出/角色参考图/ 目录，供 Seedance 视频生成时作为 image_references 传入。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

from 配置 import config as cfg
from 核心.asset_library import AssetLibrary

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 输出路径
# ═══════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHAR_REF_DIR = PROJECT_ROOT / "输出" / "角色参考图"
CHAR_REF_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# 角色肖像生成器
# ═══════════════════════════════════════════════════════════════


class CharacterPortraitGenerator:
    """调用豆包图像生成 API 为角色生成标准肖像。

    用法::

        gen = CharacterPortraitGenerator()
        gen.generate_all(asset_library)
        # → 输出/角色参考图/苏晚.png
        # → 输出/角色参考图/陆承安.png
        # → 输出/角色参考图/沈砚.png
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or cfg.IMAGE_API_KEY
        self._base_url = (base_url or cfg.IMAGE_API_BASE_URL).rstrip("/")
        self._model = model or cfg.IMAGE_MODEL

        if not self._api_key:
            logger.warning("IMAGE_API_KEY 未设置，角色肖像生成跳过")

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def generate_all(self, library: AssetLibrary) -> dict[str, Path]:
        """为资产库中所有角色生成肖像。

        Returns:
            {角色名: 图片路径} 字典
        """
        results: dict[str, Path] = {}

        # 先检查是否已有缓存的图片
        for ch in library.characters:
            cached = CHAR_REF_DIR / f"{ch.name}.png"
            if cached.is_file():
                results[ch.name] = cached
                logger.info("角色 %s 使用缓存图片: %s", ch.name, cached.name)

        new_chars = [ch for ch in library.characters if ch.name not in results]
        if not new_chars:
            return results

        if not self.enabled:
            logger.warning("API Key 未配置，跳过新角色肖像生成")
            return results

        for ch in new_chars:
            try:
                path = self._generate_one(ch)
                results[ch.name] = path
            except Exception as e:
                logger.error("角色 %s 肖像生成失败: %s", ch.name, e)

        return results

    def _generate_one(self, ch) -> Path:
        """为单个角色生成肖像。"""
        output_path = CHAR_REF_DIR / f"{ch.name}.png"

        prompt = (
            f"portrait of {ch.name}, {ch.appearance}, "
            f"{ch.visual_keywords_en}, "
            f"front view, looking at camera, clean background, "
            f"consistent character design, anime style, high quality, detailed face"
        )

        logger.info("正在生成角色肖像: %s", ch.name)

        payload = {
            "model": self._model,
            "prompt": prompt,
            "size": "1024x1024",
            "n": 1,
        }

        url = f"{self._base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)

        if resp.status_code != 200:
            raise RuntimeError(f"生图 API 失败 [{resp.status_code}]: {resp.text[:200]}")

        data = resp.json()
        b64_data = data.get("data", [{}])[0].get("b64_json", "")
        image_url = data.get("data", [{}])[0].get("url", "")

        if b64_data:
            import base64
            image_bytes = base64.b64decode(b64_data)
            output_path.write_bytes(image_bytes)
            logger.info("角色 %s 肖像已保存 (base64): %s  (%.0f KB)", ch.name, output_path.name, len(image_bytes) / 1024)
            return output_path
        elif image_url:
            r = requests.get(image_url, timeout=60)
            if r.status_code == 200:
                output_path.write_bytes(r.content)
                logger.info("角色 %s 肖像已保存 (url): %s  (%.0f KB)", ch.name, output_path.name, len(r.content) / 1024)
                return output_path
            raise RuntimeError(f"下载图片失败: {image_url}")
        else:
            raise RuntimeError(f"API 未返回图片数据: {resp.text[:200]}")


def generate_character_portraits(library: AssetLibrary) -> dict[str, Path]:
    """一键为资产库所有角色生成肖像。

    Returns:
        {角色名: 图片路径}
    """
    gen = CharacterPortraitGenerator()
    return gen.generate_all(library)
