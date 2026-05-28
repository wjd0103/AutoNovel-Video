"""AI短剧制作自动流程 Agent 工作流 —— 配置模块

加载顺序: .env 文件 > 系统环境变量 > config.py 默认值
"""

import os
from pathlib import Path
from typing import Optional

import pydantic


# ═══════════════════════════════════════════════════════════════
# 项目根路径
# ═══════════════════════════════════════════════════════════════

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
ASSETS_DIR: Path = OUTPUT_DIR / "assets"
FINAL_DIR: Path = OUTPUT_DIR / "final"


# ═══════════════════════════════════════════════════════════════
# 环境变量加载（优先级最高：.env 文件覆盖系统 env）
# ═══════════════════════════════════════════════════════════════

def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ═══════════════════════════════════════════════════════════════
# LLM 配置（DeepSeek / OpenAI 兼容接口）
# ═══════════════════════════════════════════════════════════════

LLM_API_KEY: str = _env("DEEPSEEK_API_KEY")
LLM_BASE_URL: str = _env("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL: str = _env("LLM_MODEL", "deepseek-chat")
LLM_MAX_TOKENS: int = int(_env("LLM_MAX_TOKENS", "8192"))
LLM_TEMPERATURE: float = float(_env("LLM_TEMPERATURE", "0.7"))

# ═══════════════════════════════════════════════════════════════
# 生图 API 配置
# ═══════════════════════════════════════════════════════════════

IMAGE_API_KEY: str = _env("IMAGE_API_KEY")
IMAGE_API_BASE_URL: str = _env("IMAGE_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
IMAGE_API_TYPE: str = _env("IMAGE_API_TYPE", "doubao")  # doubao / openai / stable-diffusion / comfyui
IMAGE_MODEL: str = _env("IMAGE_MODEL", "doubao-seedream-5-0-260128")

# ═══════════════════════════════════════════════════════════════
# TTS 语音合成 API 配置
# ═══════════════════════════════════════════════════════════════

TTS_API_KEY: str = _env("TTS_API_KEY")
TTS_API_BASE_URL: str = _env("TTS_API_BASE_URL", "")
TTS_API_TYPE: str = _env("TTS_API_TYPE", "openai")  # openai / edge-tts / volcengine
TTS_VOICE: str = _env("TTS_VOICE", "alloy")
TTS_SPEED: float = float(_env("TTS_SPEED", "1.0"))

# ═══════════════════════════════════════════════════════════════
# 视频生成 API 配置（Seedance 图生视频）
# ═══════════════════════════════════════════════════════════════

VIDEO_API_TYPE: str = _env("VIDEO_API_TYPE", "doubao")  # doubao (Seedance)
VIDEO_MODEL: str = _env("VIDEO_MODEL", "doubao-seedance-2-0-260128")
VIDEO_POLL_INTERVAL: float = float(_env("VIDEO_POLL_INTERVAL", "5.0"))  # 轮询间隔（秒）
VIDEO_POLL_TIMEOUT: int = int(_env("VIDEO_POLL_TIMEOUT", "600"))  # 轮询超时（秒）


# ═══════════════════════════════════════════════════════════════
# 输出参数
# ═══════════════════════════════════════════════════════════════

class OutputSettings(pydantic.BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 24
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    subtitle_enabled: bool = True


OUTPUT: OutputSettings = OutputSettings(
    width=int(_env("OUTPUT_WIDTH", "1920")),
    height=int(_env("OUTPUT_HEIGHT", "1080")),
    fps=int(_env("OUTPUT_FPS", "24")),
)


# ═══════════════════════════════════════════════════════════════
# 便捷访问
# ═══════════════════════════════════════════════════════════════

def get_config() -> "ConfigSnapshot":
    return ConfigSnapshot(
        llm_api_key=LLM_API_KEY,
        llm_base_url=LLM_BASE_URL,
        llm_model=LLM_MODEL,
        image_api_key=IMAGE_API_KEY,
        image_api_type=IMAGE_API_TYPE,
        image_model=IMAGE_MODEL,
        tts_api_key=TTS_API_KEY,
        tts_api_type=TTS_API_TYPE,
        video_model=VIDEO_MODEL,
        output=OUTPUT,
    )


class ConfigSnapshot(pydantic.BaseModel):
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    image_api_key: str
    image_api_type: str
    image_model: str
    tts_api_key: str
    tts_api_type: str
    video_model: str
    output: OutputSettings


# 确保输出目录存在
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
FINAL_DIR.mkdir(parents=True, exist_ok=True)
(ASSETS_DIR.parent / "videos").mkdir(parents=True, exist_ok=True)
(ASSETS_DIR.parent / "scripts").mkdir(parents=True, exist_ok=True)
