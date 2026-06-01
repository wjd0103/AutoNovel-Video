"""剧本处理模块 —— 全剧设定、分集大纲、分镜生成
"""

from .script_models import (
    CharacterSetting,
    EpisodeOutline,
    EpisodeStoryboard,
    SceneSetting,
    ScriptSetting,
    SeriesScript,
    ShotModel,
    ShotVideoPrompt,
)
from .script_parser import (
    save_series_script,
    save_series_script_markdown,
    save_episode_storyboard,
)
from .outline_agent import (
    OutlineAgent,
    generate_outline,
)

__all__ = [
    "CharacterSetting",
    "EpisodeOutline",
    "EpisodeStoryboard",
    "SceneSetting",
    "ScriptSetting",
    "SeriesScript",
    "ShotModel",
    "ShotVideoPrompt",
    "save_series_script",
    "save_series_script_markdown",
    "save_episode_storyboard",
    "OutlineAgent",
    "generate_outline",
]
