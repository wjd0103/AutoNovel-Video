"""音视频剪辑合成

Pipeline:
  1. 将图片序列 + 配音音频 合成为带字幕的视频片段
  2. 拼接所有片段为完整一集
  3. 叠加背景音乐、转场效果
  4. 输出最终 mp4
"""

from .composer import VideoComposer
from .subtitles import SubtitleRenderer

__all__ = ["VideoComposer", "SubtitleRenderer"]
