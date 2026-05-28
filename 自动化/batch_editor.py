#!/usr/bin/env python3
"""批量精修脚本——使用Editor Agent调整已有章节的标点风格"""

import re
import sys
import time
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("BatchEditor")

from openai import OpenAI

# ---- 配置 ----
NOVEL_NAME = "万古神龙：我的血脉全靠吞"
CHAPTERS = [1, 2, 3]
MODEL_NAME = "deepseek-v4-flash"
API_KEY = "sk-your-deepseek-api-key-here"
BASE_URL = "https://api.deepseek.com"

EDITOR_PROMPT = """你是一位专业的文字编辑，负责对小说章节进行"去 AI 味"精修。

你的工作：
  1. 保持原文的故事结构、人物对话和情节走向不变。
  2. 修正生硬的过渡句和模板化表达。
  3. 优化对话的自然度，让人物说话更像真实的人。
  4. 每段不超过 8 行，手机阅读友好。
  5. 非常重要：句子内部多用逗号连接，尽量用问号和感叹号替代句号，句号占比不要超过60%。
  6. 少用破折号进行补充说明。
  7. 确保全篇风格与已有章节一致。
  8. 检查并修正错别字和标点错误。
  9. 精简大段的场景描写，只保留精华，把过多的叙述描写合并，去掉不必要的细节。
  10. 输出前再次检查：句号占比是否超过60%，如果超过，合并句子减少句号。

输出时只输出精修后的完整章节正文，不要包含任何额外文字和注释。"""

CHAPTER_TITLES = {1: "觉醒", 2: "噬脉诀", 3: "第一次吞噬"}

def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 16384) -> str:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    last_exception = None
    for attempt in range(1, 4):
        try:
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=max_tokens,
            )
            content = resp.choices[0].message.content.strip()
            log.info(f"LLM 响应成功（尝试 {attempt}）：{len(content)} 字符")
            return content
        except Exception as e:
            last_exception = e
            log.warning(f"LLM 调用失败（尝试 {attempt}）：{e}")
            if attempt < 3:
                time.sleep(5 * attempt)
    raise RuntimeError(f"LLM 调用彻底失败：{last_exception}")

def count_punctuation(text: str) -> dict:
    """统计标点使用情况"""
    return {
        "句号": text.count("。"),
        "逗号": text.count("，"),
        "感叹号": text.count("！"),
        "问号": text.count("？"),
        "破折号": text.count("——"),
        "汉字数": len(re.findall(r'[\u4e00-\u9fff]', text)),
    }

def analyze(text: dict, label: str):
    """打印标点分析"""
    total_end = text["句号"] + text["感叹号"] + text["问号"]
    ratio = text["句号"] / total_end * 100 if total_end > 0 else 0
    log.info(f"  [{label}] 汉字: {text['汉字数']} | "
             f"句号: {text['句号']} | 逗号: {text['逗号']} | "
             f"感叹号: {text['感叹号']} | 问号: {text['问号']} | "
             f"破折号: {text['破折号']} | "
             f"句号占比: {ratio:.1f}%")

def main():
    for ch in CHAPTERS:
        title = CHAPTER_TITLES[ch]
        file_path = PROJECT_ROOT / NOVEL_NAME / "执行" / "章节" / f"第{ch:03d}章·{title}.md"

        if not file_path.exists():
            log.warning(f"文件不存在: {file_path}")
            continue

        log.info(f"\n{'='*60}")
        log.info(f"  开始精修第 {ch} 章·{title}")
        log.info(f"{'='*60}")

        original = file_path.read_text(encoding="utf-8")
        before = count_punctuation(original)
        analyze(before, "精修前")

        user_prompt = f"请精修以下章节正文，严格遵循编辑规则：\n\n{original}"

        try:
            polished = call_llm(EDITOR_PROMPT, user_prompt)
        except Exception as e:
            log.error(f"精修失败: {e}")
            continue

        after = count_punctuation(polished)
        analyze(after, "精修后")

        # 如果句号占比还是超过60%，再试一次
        total_end = after["句号"] + after["感叹号"] + after["问号"]
        ratio = after["句号"] / total_end * 100 if total_end > 0 else 0
        retry_count = 0
        while ratio > 60 and retry_count < 2:
            retry_count += 1
            log.warning(f"句号占比 {ratio:.1f}% 仍超过60%，第{retry_count}次重试精修")
            user_prompt = f"上次精修后句号占比仍为{ratio:.1f}%，请进一步减少句号，多用逗号和感叹号问号。原文：\n\n{polished}"
            try:
                polished = call_llm(EDITOR_PROMPT, user_prompt)
                after = count_punctuation(polished)
                analyze(after, f"重试#{retry_count}")
                total_end = after["句号"] + after["感叹号"] + after["问号"]
                ratio = after["句号"] / total_end * 100 if total_end > 0 else 0
            except:
                break

        # 保存结果
        file_path.write_text(polished, encoding="utf-8")
        log.info(f"✅ 已保存: {file_path.name}")

        # 打印改进
        log.info(f"  改进: 句号 {before['句号']}→{after['句号']} | "
                 f"逗号 {before['逗号']}→{after['逗号']} | "
                 f"破折号 {before['破折号']}→{after['破折号']}")

    log.info(f"\n{'='*60}")
    log.info("  全部精修完成！")
    log.info(f"{'='*60}")

if __name__ == "__main__":
    main()
