"""AI短剧制作自动流程 —— 全剧数据模型

涵盖 4 步骤所需的全部结构化数据:
  Step 1: 全剧设定 + 分集大纲
  Step 2: 每集分镜（镜头/景别/画面/时长/音频/备注）
  Step 3: 视频生成 Prompt
  Step 4: 合并输出
"""

from __future__ import annotations

from typing import Optional

import pydantic


# ═══════════════════════════════════════════════════════════════
# Step 1: 全剧设定
# ═══════════════════════════════════════════════════════════════


class CharacterSetting(pydantic.BaseModel):
    name: str = pydantic.Field(description="角色姓名")
    gender: str = pydantic.Field(description="性别")
    appearance: str = pydantic.Field(description="外貌描述（发色、瞳色、体型、服饰风格等）")
    personality: str = pydantic.Field(description="性格描述")
    voice_id: str = pydantic.Field(description="配音标识，如 male_lead / female_lead / narrator")
    voice_name: str = pydantic.Field(default="", description="TTS 音色名")


class SceneSetting(pydantic.BaseModel):
    name: str = pydantic.Field(description="场景名称")
    description: str = pydantic.Field(description="场景视觉描述（环境、色调、氛围）")


class ScriptSetting(pydantic.BaseModel):
    title: str = pydantic.Field(description="短剧名称")
    genre: str = pydantic.Field(description="剧本类型/风格，如古风玄幻 / 末世科幻 / 都市悬疑")
    visual_style: str = pydantic.Field(description="视觉风格描述，如赛博朋克霓虹色调 / 水墨国风")
    tags: list[str] = pydantic.Field(description="关键标签，如热血 / 反转 / 虐心 / 甜宠")
    bgm_description: str = pydantic.Field(description="背景音乐风格描述，如激昂交响乐 / 空灵钢琴 / 紧张电子")
    characters: list[CharacterSetting] = pydantic.Field(description="主要角色列表")
    important_scenes: list[SceneSetting] = pydantic.Field(description="重要场景列表")


class EpisodeOutline(pydantic.BaseModel):
    episode_number: int = pydantic.Field(description="集号，从 1 递增")
    title: str = pydantic.Field(description="本集标题")
    outline: str = pydantic.Field(description="本集剧情概要，100-200 字")
    estimated_duration: str = pydantic.Field(description="预估时长，如 3-5 分钟")
    cliffhanger: str = pydantic.Field(description="结尾钩子，吸引观众看下集")
    chapter_range: str = pydantic.Field(default="", description="对应原文章节范围，如 第1-3章")


class SeriesScript(pydantic.BaseModel):
    settings: ScriptSetting = pydantic.Field(description="全剧设定")
    episodes: list[EpisodeOutline] = pydantic.Field(description="分集大纲列表")


# ═══════════════════════════════════════════════════════════════
# Step 2: 每集分镜
# ═══════════════════════════════════════════════════════════════


class ShotModel(pydantic.BaseModel):
    id: int = pydantic.Field(description="分镜序号，从 1 递增")
    camera_movement: str = pydantic.Field(description="镜头运动，如 固定 / 推近 / 拉远 / 左移 / 右移 / 上摇 / 下摇 / 跟拍")
    shot_type: str = pydantic.Field(description="景别，如 远景 / 全景 / 中景 / 近景 / 特写")
    scene_content: str = pydantic.Field(description="画面内容描述（角色动作、场景环境、构图细节）")
    duration: float = pydantic.Field(description="镜头时长（秒）")
    audio_content: str = pydantic.Field(description="音频内容，包括对白、旁白、音效等")
    notes: str = pydantic.Field(default="", description="备注说明，如特效需求、转场方式")
    character_list: list[str] = pydantic.Field(default_factory=list, description="本镜出现的角色")
    voice_id: str = pydantic.Field(default="narrator", description="配音角色标识")


class EpisodeStoryboard(pydantic.BaseModel):
    episode_number: int = pydantic.Field(description="集号")
    episode_title: str = pydantic.Field(description="本集标题")
    shots: list[ShotModel] = pydantic.Field(description="分镜列表")


class SeriesStoryboard(pydantic.BaseModel):
    series_title: str = pydantic.Field(description="短剧名称")
    episodes: list[EpisodeStoryboard] = pydantic.Field(description="各集分镜")


# ═══════════════════════════════════════════════════════════════
# Step 3: 视频生成 Prompt（每镜映射）
# ═══════════════════════════════════════════════════════════════


class ShotVideoPrompt(pydantic.BaseModel):
    episode_number: int = pydantic.Field(description="集号")
    shot_id: int = pydantic.Field(description="分镜序号")
    image_prompt: str = pydantic.Field(description="AI 视频/图片生成的英文 Prompt")
    duration: float = pydantic.Field(description="时长（秒）")
    audio_text: str = pydantic.Field(description="配音文本")
    voice_id: str = pydantic.Field(default="narrator", description="配音角色")


class EpisodeVideoPlan(pydantic.BaseModel):
    episode_number: int = pydantic.Field(description="集号")
    episode_title: str = pydantic.Field(description="本集标题")
    shots: list[ShotVideoPrompt] = pydantic.Field(description="各镜视频生成计划")


from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 输出目录结构
# ═══════════════════════════════════════════════════════════════

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "输出"
SCRIPT_DIR = OUTPUT_DIR / "剧本"
EPISODE_DIR = OUTPUT_DIR / "各集"
FINAL_DIR = OUTPUT_DIR / "成片"

SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
EPISODE_DIR.mkdir(parents=True, exist_ok=True)
FINAL_DIR.mkdir(parents=True, exist_ok=True)
