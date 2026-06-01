"""剧本大纲 Agent —— 小说文本 → 全剧设定 + 分集大纲

Step 1 of the AI短剧制作自动流程:
  - 分析整部小说的设定（角色、场景、风格、BGM、标签）
  - 将故事按短视频节奏拆分为多集
  - 每集输出大纲、预估时长、结尾钩子
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

import pydantic
from openai import OpenAI

from 配置 import config as cfg
from .script_models import (
    CharacterSetting,
    EpisodeOutline,
    SceneSetting,
    ScriptSetting,
    SeriesScript,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一位专业的短剧编剧导演。你的任务是将小说文本转化为可直接用于拍摄的短剧剧本大纲。

**核心原则：**

1. **短视频节奏**：每集时长控制在 3-5 分钟。每集必须有明确的起承转合，结尾必须设置悬念钩子。

2. **全剧设定要求**：你需要从小说中提取并概括完整的全剧设定，包括：
   - 角色外貌、性格特征
   - 重要场景的视觉描述
   - 剧本风格类型
   - 关键标签
   - 背景音乐风格

3. **分集策略**：
   - 每集包含完整的小剧情弧（起承转合）
   - 每集约 3-5 分钟
   - 结尾留钩子吸引观众看下一集
   - 根据小说章节自然分段

4. **输出格式**：只输出一个合法的 JSON 对象，不要附带任何解释或 markdown 标记。

JSON 结构如下：
{
  "settings": {
    "title": "短剧名称",
    "genre": "剧本类型/风格",
    "visual_style": "视觉风格描述",
    "tags": ["关键标签1", "关键标签2"],
    "bgm_description": "背景音乐风格描述",
    "characters": [
      {
        "name": "角色名",
        "gender": "男/女",
        "appearance": "外貌描述（发色、瞳色、体型、服饰）",
        "personality": "性格描述",
        "voice_id": "male_lead/female_lead/supporting_male/supporting_female/narrator",
        "voice_name": "TTS音色名"
      }
    ],
    "important_scenes": [
      {
        "name": "场景名称",
        "description": "场景视觉描述"
      }
    ]
  },
  "episodes": [
    {
      "episode_number": 1,
      "title": "本集标题",
      "outline": "本集剧情概要 100-200字",
      "estimated_duration": "3-5分钟",
      "cliffhanger": "结尾钩子描述",
      "chapter_range": "对应原文章节范围"
    }
  ]
}
"""


# ═══════════════════════════════════════════════════════════════
# JSON 清洗与解析（复用 storyboard_agent 的逻辑）
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
# Outline Agent
# ═══════════════════════════════════════════════════════════════


class OutlineAgent:
    """剧本大纲 Agent。

    用法::

        agent = OutlineAgent()
        series_script: SeriesScript = agent.run("整本小说的文本内容...")
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
        logger.info("OutlineAgent 初始化完成  model=%s", self._model)

    def run(
        self,
        novel_text: str,
        series_title: str = "",
        extra_instructions: str = "",
    ) -> SeriesScript:
        """将整本小说转化为短剧剧本大纲。

        Args:
            novel_text: 整本小说或核心章节的文本
            series_title: 短剧名称（留空由 LLM 自动生成）
            extra_instructions: 额外指令

        Returns:
            SeriesScript 全剧设定 + 分集大纲
        """
        user_prompt = self._build_user_prompt(novel_text, series_title, extra_instructions)
        raw = self._call_api(user_prompt)
        data = _safe_json_parse(raw)
        return self._validate(data)

    def _build_user_prompt(
        self,
        novel_text: str,
        series_title: str,
        extra_instructions: str,
    ) -> str:
        parts: list[str] = ["请将以下小说文本分析并转化为短剧剧本大纲 JSON：\n"]

        if series_title:
            parts.append(f"短剧名称请使用: {series_title}\n")

        parts.append("--- 小说文本 ---")
        parts.append(novel_text)
        parts.append("--- 小说结束 ---")

        if extra_instructions:
            parts.append(f"\n额外要求: {extra_instructions}")

        return "\n".join(parts)

    def _call_api(self, user_prompt: str) -> str:
        logger.debug("调用 DeepSeek API  model=%s  prompt_len=%d", self._model, len(user_prompt))
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
    def _validate(data: dict) -> SeriesScript:
        try:
            return SeriesScript.model_validate(data)
        except pydantic.ValidationError as exc:
            error_details = []
            for err in exc.errors():
                loc = " → ".join(str(p) for p in err["loc"])
                error_details.append(f"  [{loc}] {err['msg']}")
            raise ValueError("剧本大纲 JSON 校验失败:\n" + "\n".join(error_details)) from exc


def generate_outline(
    novel_text: str,
    series_title: str = "",
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> SeriesScript:
    """一键调用生成剧本大纲。"""
    agent = OutlineAgent(api_key=api_key, model=model)
    return agent.run(novel_text, series_title=series_title)
