"""AI短剧制作自动流程 —— 核心引擎"""

from .storyboard_agent import (
    ShotModel,
    ShotStoryboardAgent,
    EpisodeStoryboard,
    SceneModel,
    StoryboardModel,
    generate_episode_storyboard,
)
from .prompt_generator import (
    PromptGenerator,
    generate_shot_prompt,
)
from .asset_library import (
    AssetLibrary,
    CharacterAsset,
    SceneAsset,
    extract_asset_library,
    build_shot_prompt_with_assets,
)
from .资产.image_generator import (
    CharacterPortraitGenerator,
    generate_character_portraits,
)
from .asset_manager import (
    AssetBatchResult,
    AssetManager,
    AssetTaskResult,
    generate_assets,
)
from .video_compiler import (
    VideoCompiler,
    compile_video,
)
from .video_generator import (
    SeedanceGenerator,
    VideoBatchResult,
    VideoTask,
    generate_video_clips,
)

__all__ = [
    "ShotModel",
    "ShotStoryboardAgent",
    "EpisodeStoryboard",
    "generate_episode_storyboard",
    "PromptGenerator",
    "generate_shot_prompt",
    "AssetLibrary",
    "CharacterAsset",
    "SceneAsset",
    "extract_asset_library",
    "build_shot_prompt_with_assets",
    "CharacterPortraitGenerator",
    "generate_character_portraits",
    "SceneModel",
    "StoryboardModel",
    "AssetManager",
    "AssetBatchResult",
    "AssetTaskResult",
    "generate_assets",
    "VideoCompiler",
    "compile_video",
    "SeedanceGenerator",
    "VideoBatchResult",
    "VideoTask",
    "generate_video_clips",
]
