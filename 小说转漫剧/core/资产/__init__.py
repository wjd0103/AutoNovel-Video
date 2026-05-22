"""多模态资产生成 & 下载

包含:
  - ImageGenerator:  调用生图 API 生成分镜图片
  - TTSGenerator:    调用 TTS API 合成配音
  - AssetDownloader: 下载 API 返回的临时 URL 到本地 assets 目录
"""

from .image_generator import ImageGenerator
from .tts_generator import TTSGenerator
from .downloader import AssetDownloader

__all__ = ["ImageGenerator", "TTSGenerator", "AssetDownloader"]
