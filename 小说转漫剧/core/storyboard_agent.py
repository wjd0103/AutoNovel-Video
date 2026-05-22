"""分镜 Agent —— 小说文本 → 结构化分镜脚本

调用 DeepSeek API，将长篇小说的章节文本转化为可被下游模块消费的
结构化 JSON 分镜数据。
"""

import json
import logging
import re
from pathlib import Path
from typing import Literal, Optional

import pydantic
from openai import OpenAI

from config import config as cfg

CameraMovement = Literal[
    "static", "pan_left", "pan_right", "zoom_in", "zoom_out", "tilt_up", "tilt_down"
]

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


class SceneModel(pydantic.BaseModel):  # pyright: ignore[reportUnannotatedClassAttribute]
    id: int = pydantic.Field(description="分镜序号，从 1 开始递增")
    character_list: list[str] = pydantic.Field(description="当前分镜中出现的角色名称列表")
    image_prompt: str = pydantic.Field(
        description=(
            "AI 绘图的英文 Prompt，必须包含画风控制词如: anime style, "
            "consistent character design, cinematic lighting, 以及具体的场景、"
            "人物动作、表情、构图描述"
        )
    )
    dialogue: str = pydantic.Field(description="该分镜对应的配音文本（对白或旁白），需精简过")
    voice_id: str = pydantic.Field(
        description="配音角色标识，如 'narrator'（旁白）、'male_lead'（男主）、'female_lead'（女主）等"
    )
    camera_movement: CameraMovement = pydantic.Field(
        description="运镜方式，限定七种: static/pan_left/pan_right/zoom_in/zoom_out/tilt_up/tilt_down"
    )


class StoryboardModel(pydantic.BaseModel):  # pyright: ignore[reportUnannotatedClassAttribute]
    series_title: str = pydantic.Field(description="剧集名称 / 本集标题")
    scenes: list[SceneModel] = pydantic.Field(description="分镜列表")


# ═══════════════════════════════════════════════════════════════
# 剧本持久化
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "output" / "scripts"
SCRIPT_DIR.mkdir(parents=True, exist_ok=True)


def save_script(storyboard: StoryboardModel, series_title: str = "") -> tuple[Path, Path]:
    """将 StoryboardModel 保存为 JSON 和人类可读的 Markdown 脚本。

    Returns:
        (json_path, md_path)
    """
    safe_title = series_title or storyboard.series_title or "untitled"
    safe_title = safe_title.replace("/", "_").replace(" ", "_")

    json_path = SCRIPT_DIR / f"{safe_title}.json"
    md_path = SCRIPT_DIR / f"{safe_title}_script.md"

    json_path.write_text(
        storyboard.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines: list[str] = [
        f"# 剧集脚本: {storyboard.series_title}",
        "",
        f"**总镜数**: {len(storyboard.scenes)}",
        "",
        "---",
        "",
    ]
    for sc in storyboard.scenes:
        chars = "、".join(sc.character_list) if sc.character_list else "（无角色）"
        lines.append(f"## 第 {sc.id} 镜")
        lines.append("")
        lines.append(f"- **运镜**: `{sc.camera_movement}`")
        lines.append(f"- **角色**: {chars}")
        lines.append(f"- **配音者**: `{sc.voice_id}`")
        lines.append(f"- **台词**: {sc.dialogue}")
        lines.append(f"- **生图 Prompt**: `{sc.image_prompt[:120]}{'…' if len(sc.image_prompt) > 120 else ''}`")
        lines.append("")
        lines.append("---")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    logger.info("剧本已保存  json=%s  md=%s", json_path.name, md_path.name)
    return json_path, md_path


# ═══════════════════════════════════════════════════════════════
# 角色描述解析
# ═══════════════════════════════════════════════════════════════

def _build_character_prompt(characters: Optional[list[dict]] = None) -> str:
    """将角色配置列表转换为注入 System Prompt 的角色一致性指令。"""
    if not characters:
        return ""

    parts: list[str] = []
    parts.append("\n\n**角色视觉设定（必须严格遵守以保证画面一致性）**：\n")
    for ch in characters:
        vid = ch.get("voice_id", "unknown")
        name = ch.get("name", vid)
        desc = ch.get("visual_desc", "").strip()
        if desc:
            parts.append(f"- voice_id={vid} ({name}): {desc}")
        else:
            parts.append(f"- voice_id={vid} ({name})")

    parts.append(
        "\n**重要**：当分镜中 character_list 包含上述角色时，你生成的 image_prompt 必须严格基于"
        "上述视觉设定描述该角色的外貌。不得自行更改发色、瞳色、体型或服装。"
        "每个含该角色的 image_prompt 中必须重复该角色的确切外貌描述关键词（如发色+服装颜色）。"
    )
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT: str = """你是一个专业的漫剧导演与分镜师。你的任务是将小说文本转化为可直接用于视频制作的分镜脚本。

**核心原则：**

1. **去除冗余描写**：过滤掉小说中大量无用的环境描写、心理独白、抒情段落，只保留推动剧情的关键信息和对白。

2. **台词精简**：将小说中的长段对白压缩为口播级短句。每句配音不超过 25 个汉字。去掉「他说道」「她轻声回答」等叙述性桥接词，只保留纯对话内容。旁白用第三人称概述，控制在 20 汉字以内。

3. **英文 Image Prompt 生成规范**：
   - 每个分镜的 image_prompt 必须为**英文**
   - **必须包含以下固定画风控制词**：`anime style, consistent character design, cinematic lighting`
   - 必须描述：场景环境（背景）、人物动作与表情、镜头构图（近景/中景/远景/特写）
   - 若该分镜有多个角色，必须描述所有角色的关键视觉特征（发色、服饰颜色、体型），并加上 `multiple characters in one frame`
   - 示例："anime style, consistent character design, cinematic lighting, close-up shot, a young man with black hair and tired eyes standing in a ruined city street at dusk, wind blowing his coat, dramatic shadows on his face"

4. **角色一致性**：`character_list` 只填写本分镜中出现在画面中的角色。`voice_id` 使用英文标识：`narrator`（旁白）、`male_lead`（男主角）、`female_lead_01`（女主角）、`supporting_male`（男配）、`supporting_female`（女配）。

5. **运镜方式**：`camera_movement` 必须从以下七种中选择：
   - `static`：静止画面，用于对话和人物特写
   - `pan_left` / `pan_right`：横向平移，用于展示场景全貌
   - `zoom_in` / `zoom_out`：推近/拉远，用于情感递进或场景过渡
   - `tilt_up` / `tilt_down`：上下摇镜，用于展示空间高度或人物俯仰关系

6. **输出格式**：只输出一个合法的 JSON 对象，不要附带任何解释或 markdown 标记。JSON 结构如下：
{
  "series_title": "剧集名称",
  "scenes": [
    {
      "id": 1,
      "character_list": ["角色A"],
      "image_prompt": "anime style, consistent character design, cinematic lighting, ...",
      "dialogue": "精简后的对白或旁白",
      "voice_id": "narrator",
      "camera_movement": "static"
    }
  ]
}

**注意**：
- 一个标准的小说章节应拆分为 8-15 个分镜
- 连续对白场景之间不要插入过多的动作描写分镜，保持对话节奏
- 每个分镜的 dialogue 必须有实际内容，不能为空字符串"""


# ═══════════════════════════════════════════════════════════════
# JSON 清洗与解析
# ═══════════════════════════════════════════════════════════════


def _extract_json(raw: str) -> str:
    """从 LLM 返回的文本中提取纯 JSON 字符串。

    处理以下情况：
    - `` ```json ... ``` `` 包裹的 markdown 代码块
    - `` ``` ... ``` `` 无语言标识的代码块
    - JSON 前后有多余的文字说明
    """
    raw = raw.strip()

    # 情况 1:  ```json ... ```
    md_json = re.search(r"```json\s*([\s\S]*?)\s*```", raw)
    if md_json:
        return md_json.group(1).strip()

    # 情况 2:  ``` ... ```（无语言标识）
    md_any = re.search(r"```\s*([\s\S]*?)\s*```", raw)
    if md_any:
        candidate = md_any.group(1).strip()
        if candidate.startswith("{") or candidate.startswith("["):
            return candidate

    # 情况 3: 直接找最外层的 { ... }  JSON 对象
    first_brace = raw.find("{")
    if first_brace == -1:
        raise ValueError("无法在 LLM 输出中找到 JSON 对象起始标记 '{'")

    last_brace = raw.rfind("}")
    if last_brace == -1 or last_brace <= first_brace:
        raise ValueError("无法在 LLM 输出中找到 JSON 对象结束标记 '}'")

    return raw[first_brace : last_brace + 1]


def _safe_json_parse(raw_text: str) -> dict:
    """安全解析 JSON，兼容常见 LLM 输出瑕疵。"""
    json_str = _extract_json(raw_text)

    # 策略 1: 直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 策略 2: 移除尾随逗号（{...,}  →  {.....}）
    cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 策略 3: 修复未闭合的引号（常见于被截断的 JSON）
    trimmed = _fix_truncated_json(cleaned)
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败，原始输出前 500 字符:\n{raw_text[:500]}") from exc


def _fix_truncated_json(json_str: str) -> str:
    """尝试修复因 token 截断导致的残缺 JSON。"""
    if json_str.endswith("}") or json_str.endswith("]"):
        return json_str

    in_string = False
    escape = False
    depth = 0
    for ch in json_str:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1

    if depth > 0:
        return json_str + '"}]'

    return json_str + '"'


# ═══════════════════════════════════════════════════════════════
# Agent 核心类
# ═══════════════════════════════════════════════════════════════


class StoryboardAgent:
    """分镜生成 Agent。

    用法::

        agent = StoryboardAgent()
        storyboard: StoryboardModel = agent.run("小说章节的文本内容...")
        print(storyboard.model_dump_json(indent=2))
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        characters: Optional[list[dict]] = None,
    ) -> None:
        self._api_key = api_key or cfg.LLM_API_KEY
        self._base_url = base_url or cfg.LLM_BASE_URL
        self._model = model or cfg.LLM_MODEL
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._characters = characters or []

        if not self._api_key:
            raise ValueError(
                "DeepSeek API Key 未设置。请在 config/.env 中设置 DEEPSEEK_API_KEY"
            )

        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        logger.info("StoryboardAgent 初始化完成  model=%s  characters=%d", self._model, len(self._characters))

    # ── 公开 API ─────────────────────────────────────────────

    def run(
        self,
        novel_text: str,
        series_title: str = "",
        extra_instructions: str = "",
    ) -> StoryboardModel:
        """将小说文本转化为分镜脚本。

        Args:
            novel_text: 小说章节原文
            series_title: 剧集标题（留空则由 LLM 自动生成）
            extra_instructions: 额外的指令，会追加到 user prompt 末尾

        Returns:
            校验后的 StoryboardModel 实例
        """
        user_prompt = self._build_user_prompt(novel_text, series_title, extra_instructions)
        raw = self._call_api(user_prompt)
        data = _safe_json_parse(raw)
        return self._validate(data)

    def run_raw(
        self,
        novel_text: str,
        series_title: str = "",
        extra_instructions: str = "",
    ) -> str:
        """与 run 相同但不校验，直接返回 LLM 原始文本。用于调试。"""
        user_prompt = self._build_user_prompt(novel_text, series_title, extra_instructions)
        return self._call_api(user_prompt)

    def run_json(
        self,
        novel_text: str,
        series_title: str = "",
        extra_instructions: str = "",
    ) -> dict:
        """与 run 相同但返回原始 dict（不经 Pydantic 校验）。用于调试。"""
        user_prompt = self._build_user_prompt(novel_text, series_title, extra_instructions)
        raw = self._call_api(user_prompt)
        return _safe_json_parse(raw)

    # ── 内部方法 ─────────────────────────────────────────────

    def _build_user_prompt(
        self,
        novel_text: str,
        series_title: str,
        extra_instructions: str,
    ) -> str:
        parts: list[str] = ["请将以下小说文本转化为分镜脚本 JSON：\n"]

        if series_title:
            parts.append(f"剧集标题请使用: {series_title}\n")

        if self._characters:
            parts.append("--- 角色视觉设定 ---")
            for ch in self._characters:
                vid = ch.get("voice_id", "?")
                name = ch.get("name", vid)
                desc = ch.get("visual_desc", "").strip()
                voice = ch.get("voice_name", "")
                parts.append(f"{vid} ({name}, TTS音色={voice}): {desc}")
            parts.append("--- 角色设定结束 ---\n")

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
    def _validate(data: dict) -> StoryboardModel:
        """Pydantic 校验并返回模型实例。"""
        try:
            storyboard = StoryboardModel.model_validate(data)
        except pydantic.ValidationError as exc:
            error_details = []
            for err in exc.errors():
                loc = " → ".join(str(p) for p in err["loc"])
                error_details.append(f"  [{loc}] {err['msg']}")
            raise ValueError(
                "分镜 JSON 校验失败:\n" + "\n".join(error_details)
            ) from exc

        scene_count = len(storyboard.scenes)
        if scene_count < 3:
            logger.warning("分镜数量仅 %d 个，可能拆解不足", scene_count)
        logger.info("分镜校验通过  共 %d 个分镜  剧集: %s", scene_count, storyboard.series_title)
        return storyboard


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def generate_storyboard(
    novel_text: str,
    series_title: str = "",
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    characters: Optional[list[dict]] = None,
) -> StoryboardModel:
    """一行调用生成分镜脚本。

    Args:
        novel_text: 小说章节文本
        series_title: 剧集标题
        api_key: DeepSeek API Key（不传则从环境变量读取）
        model: 模型名称（不传则使用默认 deepseek-chat）
        characters: 角色配置列表（用于注入角色一致指令）
    """
    agent = StoryboardAgent(api_key=api_key, model=model, characters=characters)
    return agent.run(novel_text, series_title=series_title)
