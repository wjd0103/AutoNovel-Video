"""AI短剧制作自动流程 —— 核心引擎"""

from .asset_manager import (
    AssetBatchResult,
    AssetManager,
    AssetTaskResult,
    generate_assets,
    generate_character_and_scene_image,
    generate_voice_tts,
)
from .storyboard_agent import (
    CameraMovement,
    SceneModel,
    StoryboardAgent,
    StoryboardModel,
    generate_storyboard,
    save_script,
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
    "StoryboardAgent",
    "StoryboardModel",
    "SceneModel",
    "CameraMovement",
    "generate_storyboard",
    "save_script",
    "AssetManager",
    "AssetBatchResult",
    "AssetTaskResult",
    "generate_assets",
    "generate_character_and_scene_image",
    "generate_voice_tts",
    "VideoCompiler",
    "compile_video",
    "SeedanceGenerator",
    "VideoBatchResult",
    "VideoTask",
    "generate_video_clips",
]
