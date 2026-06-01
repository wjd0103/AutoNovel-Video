"""分镜 Agent —— 按集生成分镜脚本

Step 2 of the AI短剧制作自动流程:
  按每一集的内容生成详细分镜，每镜包含：
  - 镜头运动（固定/推近/拉远/平移/摇镜）
  - 景别（远景/全景/中景/近景/特写）
  - 画面内容描述
  - 时长（秒）
  - 音频内容（对白/旁白/音效）
  - 备注说明
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import pydantic
from openai import OpenAI

from 配置 import config as cfg

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Step 2 数据模型
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


# ═══════════════════════════════════════════════════════════════
# 兼容旧版 SceneModel / StoryboardModel（复用现有资产/合成模块）
# ═══════════════════════════════════════════════════════════════

CameraMovement = str

class SceneModel(pydantic.BaseModel):
    id: int
    character_list: list[str]
    image_prompt: str
    dialogue: str
    voice_id: str
    camera_movement: CameraMovement
    duration: float = 3.0
    shot_type: str = "中景"
    notes: str = ""


class StoryboardModel(pydantic.BaseModel):
    series_title: str
    scenes: list[SceneModel]


# ═══════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位专业的短剧分镜师。你的任务是根据剧本大纲和小说内容，为每一集生成详细的分镜脚本。

**核心原则：**

1. **分镜规范**：每个分镜必须包含以下字段：
   - `camera_movement`：镜头运动方式，可选：固定 / 推近 / 拉远 / 左移 / 右移 / 上摇 / 下摇 / 跟拍
   - `shot_type`：景别，可选：远景 / 全景 / 中景 / 近景 / 特写
   - `scene_content`：画面内容描述，详细描述角色动作、表情、场景环境
   - `duration`：镜头时长（秒），对话镜头 3-5 秒，动作镜头 2-3 秒，空镜 2-4 秒
   - `audio_content`：音频内容，对白写具体台词，旁白用第三人称，音效用【】标注
   - `notes`：备注，如特效需求、转场方式等
   - `character_list`：本镜出现的角色名列表
   - `voice_id`：配音角色标识

2. **分镜数量**：每集根据内容长度拆分为 12-25 个分镜。

3. **节奏把控**：
   - 开篇 3 镜内需吸引观众注意力（可用悬念/冲突/视觉冲击）
   - 对话场景用中景+近景交替，配合正反打
   - 动作场景用全景+特写交替，配合运动镜头
   - 每集结尾 2 镜需制造悬念钩子

4. **景别运用**：
   - 远景：展示大环境、空间关系
   - 全景：展示角色全身及周围环境
   - 中景：角色腰部以上，适合对话
   - 近景：角色胸部以上，表现情绪
   - 特写：强调细节（眼神、手部、道具）

5. **输出格式**：只输出一个合法的 JSON 对象。JSON 结构如下：
{
  "episode_number": 1,
  "episode_title": "本集标题",
  "shots": [
    {
      "id": 1,
      "camera_movement": "固定",
      "shot_type": "远景",
      "scene_content": "画面内容描述",
      "duration": 4.0,
      "audio_content": "音频内容",
      "notes": "备注",
      "character_list": ["角色A"],
      "voice_id": "narrator"
    }
  ]
}
"""


# ═══════════════════════════════════════════════════════════════
# JSON 清洗与解析
# ═══════════════════════════════════════════════════════════════


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    md_json = re.search(r"```json\s*([\s\S]*?)\s*```", raw)
    if md_json:
        return md_json.group(1).strip()
    md_any = re.search(r"```\s*([\s\S]*?)\s*```", raw)
    if md_any:
        candidate = md_any.group(1).strip()
        if candidate.startswith("{") or candidate.startswith("["):
            return candidate
    first_brace = raw.find("{")
    if first_brace == -1:
        raise ValueError("无法在 LLM 输出中找到 JSON 对象起始标记 '{'")
    last_brace = raw.rfind("}")
    if last_brace == -1 or last_brace <= first_brace:
        raise ValueError("无法在 LLM 输出中找到 JSON 对象结束标记 '}'")
    return raw[first_brace : last_brace + 1]


def _safe_json_parse(raw_text: str) -> dict:
    json_str = _extract_json(raw_text)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败，原始输出前 500 字符:\n{raw_text[:500]}") from exc


# ═══════════════════════════════════════════════════════════════
# 分镜 Agent
# ═══════════════════════════════════════════════════════════════


class ShotStoryboardAgent:
    """分镜生成 Agent（Step 2）。

    用法::

        agent = ShotStoryboardAgent()
        episode_storyboard = agent.run("本集小说文本", episode_title="第1集")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> None:
        self._api_key = api_key or cfg.LLM_API_KEY
        self._base_url = base_url or cfg.LLM_BASE_URL
        self._model = model or cfg.LLM_MODEL
        self._temperature = temperature
        self._max_tokens = max_tokens

        if not self._api_key:
            raise ValueError("API Key 未设置")

        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        logger.info("ShotStoryboardAgent 初始化完成  model=%s", self._model)

    def run(
        self,
        episode_text: str,
        episode_number: int = 1,
        episode_title: str = "",
        series_setting: Optional[str] = None,
        extra_instructions: str = "",
    ) -> EpisodeStoryboard:
        """将一集小说文本转化为分镜脚本。

        Args:
            episode_text: 本集对应的小说原文
            episode_number: 集号
            episode_title: 本集标题
            series_setting: 全剧设定 JSON 字符串，用于角色/场景一致性
            extra_instructions: 额外指令

        Returns:
            EpisodeStoryboard 本集分镜
        """
        user_prompt = self._build_user_prompt(
            episode_text, episode_number, episode_title, series_setting, extra_instructions
        )
        raw = self._call_api(user_prompt)
        data = _safe_json_parse(raw)
        return self._validate(data, episode_number, episode_title)

    def _build_user_prompt(
        self,
        episode_text: str,
        episode_number: int,
        episode_title: str,
        series_setting: Optional[str],
        extra_instructions: str,
    ) -> str:
        parts: list[str] = []

        if series_setting:
            parts.append("--- 全剧设定（参考角色和场景描述）---")
            parts.append(series_setting)
            parts.append("--- 全剧设定结束 ---\n")

        parts.append(f"请为第 {episode_number} 集生成分镜脚本")
        if episode_title:
            parts.append(f"（标题：{episode_title}）")
        parts.append("：\n")

        parts.append("--- 本集小说文本 ---")
        parts.append(episode_text)
        parts.append("--- 小说结束 ---")

        if extra_instructions:
            parts.append(f"\n额外要求: {extra_instructions}")

        return "\n".join(parts)

    def _call_api(self, user_prompt: str) -> str:
        logger.debug("调用 API  model=%s  prompt_len=%d", self._model, len(user_prompt))
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        content = response.choices[0].message.content or ""
        logger.info("API 返回  tokens_used=%d", response.usage.total_tokens if response.usage else 0)
        return content

    @staticmethod
    def _validate(data: dict, episode_number: int, episode_title: str) -> EpisodeStoryboard:
        data.setdefault("episode_number", episode_number)
        data.setdefault("episode_title", episode_title)
        try:
            return EpisodeStoryboard.model_validate(data)
        except pydantic.ValidationError as exc:
            error_details = []
            for err in exc.errors():
                loc = " → ".join(str(p) for p in err["loc"])
                error_details.append(f"  [{loc}] {err['msg']}")
            raise ValueError("分镜 JSON 校验失败:\n" + "\n".join(error_details)) from exc


def generate_episode_storyboard(
    episode_text: str,
    episode_number: int = 1,
    episode_title: str = "",
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    series_setting: Optional[str] = None,
) -> EpisodeStoryboard:
    """一键调用生成一集的分镜。"""
    agent = ShotStoryboardAgent(api_key=api_key, model=model)
    return agent.run(episode_text, episode_number=episode_number, episode_title=episode_title, series_setting=series_setting)
