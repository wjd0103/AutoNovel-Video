"""小说情节拆解 & 分镜脚本生成

Pipeline:
  1. 读取原始小说章节
  2. LLM 拆解为 「场景 → 镜头 → 对白/旁白」
  3. 为每个镜头生成出图 Prompt 和配音文本
  4. 输出结构化分镜脚本（JSON / Pydantic Model）
"""

from .script_parser import ScriptParser
from .prompt_builder import PromptBuilder

__all__ = ["ScriptParser", "PromptBuilder"]
