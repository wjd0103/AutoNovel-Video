#!/usr/bin/env python3
"""
小说创作导演系统（ReAct 循环）
=============================
基于 Thought-Action-Observation 循环的多 Agent 协作框架。

系统角色：
  - Director（总导演）：输出 JSON 决策，唤醒 Writer / Editor / Ops
  - Writer（写手）：    读取记忆+大纲，生成章节正文
  - Editor（编辑）：    读取风格指南，精修去 AI 味
  - Ops（运维）：       调用发布工具

用法：
    python 自动化/agent_director.py --novel 万古神龙 --target 77
"""

import re
import os
import sys
import json
import time
import logging
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT / "自动化" / "日志"
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"director_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("NovelKingdom")

MAX_RETRIES = 3
RETRY_DELAY = 5

# ---- 从项目配置读取 API 凭证 ----
PROJECT_CONFIG_FILE = PROJECT_ROOT / "万古神龙：我的血脉全靠吞" / "项目配置.md"
_OPENAI_API_KEY = "sk-84b0c3b8a1114b11bf020b646b1627a9"
_OPENAI_BASE_URL = "https://api.deepseek.com"
_OPENAI_MODEL = "deepseek-v4-flash"

if PROJECT_CONFIG_FILE.exists():
    cfg_text = PROJECT_CONFIG_FILE.read_text(encoding="utf-8")
    # 解析 api 密钥
    m = re.search(r'api 密钥[：:]\s*(\S+)', cfg_text)
    if m:
        _OPENAI_API_KEY = m.group(1).strip()
    # 解析 api 地址
    m = re.search(r'api 地址[：:]\s*(\S+)', cfg_text)
    if m:
        _OPENAI_BASE_URL = m.group(1).strip().rstrip("/")
    # 解析模型 id
    m = re.search(r'模型 id[：:]\s*(\S+)', cfg_text)
    if m:
        _OPENAI_MODEL = m.group(1).strip()

OPENAI_API_KEY = _OPENAI_API_KEY
OPENAI_BASE_URL = _OPENAI_BASE_URL
MODEL_NAME = _OPENAI_MODEL

log.info(f"加载配置: API={OPENAI_BASE_URL}, Model={MODEL_NAME}, Key={'已设置' if OPENAI_API_KEY else '未设置'}")

from 脚本.tools import (
    read_project_file,
    write_chapter_file,
    publish_to_platform,
)


# ============================================================
# LLM 调用封装
# ============================================================

def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    response_format: Optional[dict] = None,
) -> str:
    """调用 DeepSeek（通过 openai 库），内置重试与异常保护。"""
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    kwargs = dict(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_format:
        kwargs["response_format"] = response_format

    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content.strip()
            log.info(f"LLM 响应成功（尝试 {attempt}）：{len(content)} 字符")
            return content
        except Exception as e:
            last_exception = e
            log.warning(f"LLM 调用失败（尝试 {attempt}/{MAX_RETRIES}）：{e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(
        f"LLM 调用彻底失败，已重试 {MAX_RETRIES} 次：{last_exception}"
    )


# ============================================================
# 记忆加载
# ============================================================

def load_memory(novel_name: str) -> str:
    """加载小说的全部记忆文件，拼成上下文。"""
    novel_dir = PROJECT_ROOT / novel_name
    memory_dir = novel_dir / "记忆"

    paths = [
        memory_dir / "世界观" / "世界背景.md",
        memory_dir / "世界观" / "力量体系.md",
        memory_dir / "人物卡" / "主角-姜尘.md",
        memory_dir / "人物卡" / "关键配角.md",
        memory_dir / "剧情线" / "主线.md",
    ]

    parts = []
    for p in paths:
        if p.exists():
            text = p.read_text(encoding="utf-8")
            parts.append(f"===== {p.relative_to(memory_dir)} =====\n{text}")

    if not parts:
        log.warning(f"未找到记忆文件: {memory_dir}")
        return ""
    return "\n\n".join(parts)


def load_latest_chapters(novel_name: str, count: int = 5) -> str:
    """加载最近 N 章的正文内容供上下文参考。"""
    chapters_dir = PROJECT_ROOT / novel_name / "执行" / "章节"
    if not chapters_dir.exists():
        return ""

    files = sorted(chapters_dir.glob("第*.md"))
    files = files[-count:]

    parts = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        parts.append(f"===== {f.name} =====\n{text}")
    return "\n\n".join(parts)


def load_outline(novel_name: str) -> str:
    """加载策划大纲。"""
    path = PROJECT_ROOT / novel_name / "策划" / "大纲.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    log.warning(f"大纲文件不存在: {path}")
    return ""


def load_style_guide() -> str:
    """加载校对风格指南。"""
    path = PROJECT_ROOT / "校对" / "风格指南.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    log.warning(f"风格指南不存在: {path}")
    return ""


def quality_check(content: str) -> str:
    """对生成的章节执行质检，返回质检报告。

    校验规则与 校对/风格指南.md 强制标准同步：
      - 字数底线 > 3000（一票否决）
      - 16 类违禁词清洗（>= 3 次即不合格）
      - 段落格式检查（一句话一段，句号分段）
      - 句号使用检查（少用句号，多用逗号感叹号问号）
      - 破折号使用检查（少用破折号补充说明）
      - 章节钩子检查（最后一段需要悬念/转折/预告）
    """
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", content))
    report_lines = []

    # ===== 字数检查 =====
    report_lines.append("=== 字数检查 ===")
    report_lines.append(f"汉字数: {chinese_chars}")
    report_lines.append(f"标准: > 3000")
    if chinese_chars < 3000:
        report_lines.append(
            f"结果: ❌ 未达标（当前{chinese_chars} < 3000，打回重写）"
        )
    elif chinese_chars > 6000:
        report_lines.append(
            f"结果: ⚠️ 超出（当前{chinese_chars} > 6000，建议拆分）"
        )
    else:
        report_lines.append("结果: ✅ 达标")

    # ===== 违禁词检查 =====
    report_lines.append("\n=== 违禁词检查 ===")
    forbidden = [
        ("BW-01", "不得不说"),
        ("BW-02", "某种意义上"),
        ("BW-03", "嘴角微微上扬"),
        ("BW-04", "眼神中闪过一丝复杂"),
        ("BW-05", "仿佛"),
        ("BW-05", "好似"),
        ("BW-05", "宛如"),
        ("BW-06", "微微"),
        ("BW-06", "轻轻"),
        ("BW-06", "淡淡地"),
        ("BW-07", "某种"),
        ("BW-08", "似乎"),
        ("BW-08", "好像"),
        ("BW-09", "就在这时"),
        ("BW-10", "忽然"),
        ("BW-10", "突然"),
        ("BW-11", "心中一惊"),
        ("BW-11", "心头一凛"),
        ("BW-12", "深吸一口气"),
        ("BW-13", "一股暖流"),
        ("BW-13", "一股寒意"),
        ("BW-14", "空气仿佛凝固"),
        ("BW-15", "说不清道不明"),
        ("BW-16", "不知为何"),
    ]
    found_banned = []
    for code, word in forbidden:
        c = content.count(word)
        if c > 0:
            found_banned.append((code, word, c))

    if found_banned:
        # 按编号合并统计
        from collections import Counter
        code_counter = Counter(code for code, _, _ in found_banned)
        total_codes = len(code_counter)

        for code, word, c in found_banned:
            report_lines.append(f"  {code}「{word}」→ 出现 {c} 次")

        if total_codes >= 3:
            report_lines.append(
                f"结果: ❌ 不合格（{total_codes} 类违禁词 >= 3，打回精修）"
            )
        else:
            report_lines.append(
                f"结果: ⚠️ 注意（{total_codes} 类违禁词，建议精修）"
            )
    else:
        report_lines.append("结果: ✅ 无违禁词")

    # ===== 段落格式检查（一句话一段，句号分段）=====
    report_lines.append("\n=== 段落格式检查 ===")
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    multi_sentence_paragraphs = 0
    
    for para in paragraphs:
        sentence_count = sum(1 for char in para if char in "。！？")
        if sentence_count > 1:
            multi_sentence_paragraphs += 1
    
    if multi_sentence_paragraphs == 0:
        report_lines.append(f"结果: ✅ 所有段落都是一句话一段，句号分段")
    else:
        report_lines.append(f"结果: ⚠️ 发现 {multi_sentence_paragraphs} 个段落包含多句话，建议改为一句话一段")

    # ===== 句号使用检查（少用句号，多用逗号感叹号问号）=====
    report_lines.append("\n=== 句号使用检查 ===")
    period_count = content.count("。")
    comma_count = content.count("，")
    exclamation_count = content.count("！")
    question_count = content.count("？")
    total_end_punctuation = period_count + exclamation_count + question_count
    
    if total_end_punctuation > 0:
        period_ratio = period_count / total_end_punctuation
        if period_ratio < 0.6:
            report_lines.append(f"结果: ✅ 句号使用合理（句号占比 {period_ratio:.1%}，其他标点丰富）")
        else:
            report_lines.append(f"结果: ⚠️ 句号使用过多（句号占比 {period_ratio:.1%}），建议多用逗号、感叹号、问号")
    else:
        report_lines.append("结果: ⚠️ 未检测到足够的标点符号")
    
    report_lines.append(f"  句号: {period_count} | 逗号: {comma_count} | 感叹号: {exclamation_count} | 问号: {question_count}")

    # ===== 破折号使用检查（少用破折号补充说明）=====
    report_lines.append("\n=== 破折号使用检查 ===")
    dash_count = content.count("——")
    if dash_count == 0:
        report_lines.append("结果: ✅ 未使用破折号")
    elif dash_count <= 3:
        report_lines.append(f"结果: ⚠️ 破折号使用 {dash_count} 次，数量适中")
    else:
        report_lines.append(f"结果: ❌ 破折号使用过多（{dash_count} 次），建议减少使用破折号补充说明")

    # ===== 章节钩子检查 =====
    report_lines.append("\n=== 章节钩子检查 ===")
    last_200 = content[-200:] if len(content) > 200 else content
    hook_keywords = ["没有", "即将", "突然", "下一个", "等待", "不知", "会怎样",
                     "一刻", "前方", "明天", "新的", "风暴", "不安", "预感",
                     "黎明", "黑暗", "将", "即将", "未来", ""]
    has_hook = any(kw in last_200 for kw in hook_keywords if kw)
    if has_hook:
        report_lines.append("结果: ✅ 结尾包含钩子（悬念/转折/预告）")
    else:
        report_lines.append("结果: ⚠️ 未检测到明显钩子，建议在章节结尾添加悬念")

    return "\n".join(report_lines)


# ============================================================
# NovelKingdomHarness
# ============================================================

class NovelKingdomHarness:
    """小说创作导演系统——基于 ReAct 循环的多 Agent 协作框架。"""

    DIRECTOR_SYSTEM_PROMPT = """你是一位经验丰富的小说创作总导演。你的职责是编排整个创作流程。

输出格式必须是 JSON（不要包含任何其他文字）：
{
    "thought": "你对当前状态的思考和分析",
    "call_agent": "Writer|Editor|None",
    "tool_to_use": "工具名称",
    "tool_args": { "key": "value" }
}

可选 agent：
  - Writer：写手。当你确认需要生成新章节正文时唤醒。
    此时 tool_to_use = "generate_chapter"
    tool_args 中包含 chapter_num（章节号）、chapter_title（章节标题，2-4个字）、key_plot_points（关键剧情点）。

  - Editor：编辑。当你认为刚生成的正文需要精修时唤醒。
    此时 tool_to_use = "polish_chapter"
    tool_args 中包含 chapter_num 和 feedback（导演的修改意见）。

  - None：当全部工作完成时输出。

核心规则：
  1. 每轮只能唤醒一个 agent。
  2. Writer 生成后必须切换到 Editor 去精修。
  3. Editor 确认精修完成后 -> 调用 write_chapter_file 写入文件 -> 输出 None 结束流程。
  4. 如果字数不足或质量不达标，打回 Writer 重写。"""

    WRITER_SYSTEM_PROMPT = """你是一位资深网络小说作家，负责撰写网络小说章节正文。

核心规则：正文以第一行直接开头，不包含任何标题行、标记行或注释。

写作要求：
  1. 每章字数：3000-4500 汉字（硬性标准）。
  2. 正文从第一行直接开始写故事，不要写 "# 第N章"、"【标题】" 等任何标题行。
  3. 每段不超过 8 行，手机阅读友好。
  4. 非常重要：句子内部多用逗号连接，尽量用问号和感叹号替代句号，句号占比不要超过60%。
  5. 少用破折号进行补充说明。
  6. 对话独立成段。
  7. 不要使用 Markdown 标题格式。
  8. 保持稳定的叙事节奏，每章结尾留钩子。
  9. 人物行动和对话要符合人物性格设定。

输出时只输出章节正文，不要包含任何额外文字和注释。"""

    EDITOR_SYSTEM_PROMPT = """你是一位专业的文字编辑，负责对小说章节进行"去 AI 味"精修。

你的工作：
  1. 保持原文的故事结构、人物对话和情节走向不变。
  2. 修正生硬的过渡句和模板化表达。
  3. 优化对话的自然度，让人物说话更像真实的人。
  4. 调整段落节奏，每段不超过 8 行，手机阅读友好。
  5. 非常重要：句子内部多用逗号连接，尽量用问号和感叹号替代句号，句号占比不要超过60%。
  6. 少用破折号进行补充说明。
  7. 确保全篇风格与已有章节一致。
  8. 检查并修正错别字和标点错误。

输出时只输出精修后的完整章节正文，不要包含任何额外文字和注释。"""

    def __init__(self, novel_name: str, target_chapter: int):
        self.novel_name = novel_name
        self.target_chapter = target_chapter
        self.current_chapter = target_chapter
        self.generated_content: Optional[str] = None
        self.edited_content: Optional[str] = None
        self.written_path: Optional[str] = None
        self._pending_title: str = ""
        self.iteration_count = 0
        self.max_iterations = 30

        self.memory_context = load_memory(novel_name)
        self.outline = load_outline(novel_name)
        self.style_guide = load_style_guide()
        self.latest_chapters = load_latest_chapters(novel_name, count=3)

        log.info(f"NovelKingdomHarness 初始化完成")
        log.info(f"  小说: {novel_name} | 目标章节: 第{target_chapter}章")
        log.info(f"  记忆: {len(self.memory_context)} 字符")
        log.info(f"  大纲: {len(self.outline)} 字符")
        log.info(f"  风格指南: {len(self.style_guide)} 字符")

    # ---- 核心入口 ----

    def start_work(self) -> str:
        """启动创作导演循环。"""
        log.info("=" * 60)
        log.info(f"  启动创作导演循环 — 目标: 第{self.target_chapter}章")
        log.info("=" * 60)

        observation = f"启动系统，准备生成第{self.target_chapter}章。写作大纲摘要：{self.outline[:500]}"

        while self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            log.info(f"\n{'='*60}")
            log.info(f"  循环迭代 #{self.iteration_count}")
            log.info(f"{'='*60}")

            try:
                decision = self._director_think(observation)
                log.info(
                    f"  导演决策: {json.dumps(decision, ensure_ascii=False, indent=2)}"
                )

                call_agent = decision.get("call_agent", "None")
                tool_args = decision.get("tool_args", {})

                if call_agent == "None":
                    # 如果已精修完毕且未写入文件，自动写入
                    if self.edited_content and not self.written_path:
                        self._write_final_file()
                    log.info("  导演指示：工作完成，退出循环")
                    break
                elif call_agent == "Writer":
                    observation = self._run_writer(tool_args)
                elif call_agent == "Editor":
                    observation = self._run_editor(tool_args)
                else:
                    observation = f"未知 agent: {call_agent}，跳过"

                log.info(f"  观察结果: {observation[:300]}...")

            except json.JSONDecodeError as e:
                observation = f"导演输出 JSON 解析失败: {e}，重试"
                log.warning(observation)
                continue
            except Exception as e:
                log.error(f"循环异常: {e}")
                log.error(traceback.format_exc())
                observation = f"系统异常: {e}，重试"
                time.sleep(RETRY_DELAY)
                continue

        summary = self._generate_summary()
        log.info(f"\n{'='*60}")
        log.info(f"  创作流程结束\n{summary}")
        log.info(f"{'='*60}")
        return summary

    # ---- Director ----

    def _director_think(self, observation: str) -> dict:
        """调用 Director 大模型进行思考决策。"""
        has_gen = "✅ 已生成" if self.generated_content else "❌ 未生成"
        has_edt = "✅ 已编辑" if self.edited_content else "❌ 未编辑"
        has_written = "✅ 已写入文件" if self.written_path else "❌ 未写入"

        user_prompt = f"""【当前项目】
小说名称：{self.novel_name}
目标章节：第{self.target_chapter}章
当前迭代：#{self.iteration_count}

【上一步观察】
{observation}

【当前进度】
已生成内容：{has_gen}
已编辑内容：{has_edt}
已写入文件：{has_written}

请根据当前状态输出 JSON 决策。"""

        raw = call_llm(
            system_prompt=self.DIRECTOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise

    # ---- Writer ----

    def _run_writer(self, args: dict) -> str:
        """执行 Writer 写手任务——生成章节正文。"""
        chapter_num = args.get("chapter_num", self.current_chapter)
        chapter_title = args.get("chapter_title", "")
        key_plot_points = args.get("key_plot_points", "")

        # 保存标题供后续写入使用
        self._pending_title = chapter_title

        log.info(f"  [Writer] 开始生成第{chapter_num}章...")

        user_prompt = f"""请为《{self.novel_name}》生成第{chapter_num}章的正文。

【大纲信息】
{self.outline[:2000]}

【记忆/世界观】
{self.memory_context[:2000]}

【最近章节回顾】
{self.latest_chapters[:3000]}

【本集关键剧情点】
{key_plot_points if key_plot_points else "请根据大纲和上文的剧情发展自然地推进故事。"}

【风格指南要点】
{self.style_guide[:1000]}

请直接输出章节正文，不要包含标题行，字数 3000-4500 汉字。"""

        content = call_llm(
            system_prompt=self.WRITER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.8,
            max_tokens=8192,
        )

        content = re.sub(r"^#\s+第\d+章.*?\n", "", content).strip()

        self.generated_content = content
        self.current_chapter = chapter_num

        report = quality_check(content)
        log.info(f"  [Writer] 生成完成 | 质检:\n{report}")

        return f"Writer 已完成第{chapter_num}章生成。{report}"

    # ---- Editor ----

    def _run_editor(self, args: dict) -> str:
        """执行 Editor 编辑任务——精修章节。"""
        chapter_num = args.get("chapter_num", self.current_chapter)
        feedback = args.get("feedback", "")

        source_content = self.edited_content or self.generated_content
        if not source_content:
            return "ERROR: 没有可编辑的内容（还未生成），请先调用 Writer。"

        log.info(f"  [Editor] 开始精修第{chapter_num}章...")

        user_prompt = f"""请精修以下章节正文。

【风格指南】
{self.style_guide[:1500]}

【导演的修改意见】
{feedback if feedback else "请根据风格指南进行常规精修。重点关注：去除生硬感，优化对话自然度，调整段落节奏。"}

【原文】
{source_content}

请输出精修后的完整章节正文。"""

        edited = call_llm(
            system_prompt=self.EDITOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.5,
            max_tokens=8192,
        )

        edited = edited.strip()
        self.edited_content = edited

        report = quality_check(edited)
        log.info(f"  [Editor] 精修完成 | 质检:\n{report}")

        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", edited))
        if chinese_chars < 3000:
            return (
                f"Editor 已完成精修，但字数不足（{chinese_chars} < 3000），"
                f"需要打回 Writer 扩充。{report}"
            )
        return f"Editor 已完成精修，字数达标（{chinese_chars} 汉字）。{report}"

    # ---- Ops ----

    def _run_ops(self, args: dict) -> str:
        """执行 Ops 运维任务——写入文件并发布。"""
        chapter_num = args.get("chapter_num", self.current_chapter)

        final_content = self.edited_content or self.generated_content
        if not final_content:
            return "ERROR: 没有可用于发布的内容。"

        try:
            filepath = write_chapter_file(
                novel_name=self.novel_name,
                chapter_num=chapter_num,
                content=final_content,
            )
            self.generated_path = filepath
            log.info(f"  [Ops] 章节已写入: {filepath}")
        except Exception as e:
            return f"ERROR: 写入章节文件失败: {e}"

        try:
            result = publish_to_platform(
                novel_name=self.novel_name,
                chapter_path=filepath,
            )
            log.info(f"  [Ops] 发布结果: {result}")

            if result.startswith("SUCCESS"):
                self.generated_content = None
                self.edited_content = None
                self.generated_path = None
                self.current_chapter = chapter_num + 1

            return f"Ops 操作完成: {result}"

        except Exception as e:
            return f"ERROR: 发布失败: {e}"

    # ---- 写入文件（替代 Ops） ----

    def _write_final_file(self) -> str:
        """精修完成后写入章节文件。"""
        final_content = self.edited_content or self.generated_content
        if not final_content:
            return ""

        try:
            filepath = write_chapter_file(
                novel_name=self.novel_name,
                chapter_num=self.current_chapter,
                content=final_content,
                title=self._pending_title,
            )
            self.written_path = filepath
            log.info(f"  [写入] 章节已写入: {filepath}")
            return filepath
        except Exception as e:
            log.error(f"  [写入] 写入失败: {e}")
            return ""

    # ---- 辅助 ----

    def _generate_summary(self) -> str:
        """生成最终状态摘要。"""
        return (
            f"  小说: {self.novel_name}\n"
            f"  目标章节: 第{self.target_chapter}章\n"
            f"  迭代次数: {self.iteration_count}\n"
            f"  已生成内容: {'✅' if self.generated_content else '❌'}\n"
            f"  已编辑内容: {'✅' if self.edited_content else '❌'}\n"
            f"  已写入文件: {'✅' if self.written_path else '❌'}"
        )


# ============================================================
# 命令行入口
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="小说创作导演系统")
    parser.add_argument(
        "--novel",
        type=str,
        default="万古神龙：我的血脉全靠吞",
        help="小说名称（文件夹名）",
    )
    parser.add_argument(
        "--target",
        type=int,
        required=True,
        help="目标章节号",
    )
    args = parser.parse_args()

    harness = NovelKingdomHarness(
        novel_name=args.novel,
        target_chapter=args.target,
    )
    summary = harness.start_work()

    print("\n" + "=" * 60)
    print("  最终状态")
    print(summary)
    print("=" * 60)


if __name__ == "__main__":
    main()
