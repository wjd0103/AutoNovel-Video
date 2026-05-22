#!/usr/bin/env python3
"""
万古神龙：我的血脉全靠吞 —— 章节内容优化脚本

优化规则：
1. 对话与叙事衔接：`！"` 或 `。"` 后直接跟非归属叙事时，用 `——` 分隔
2. 段落换行规范化：段落间统一用空行分隔
3. 叙事句末标点统一：在纯叙事段落中，将句末的！改为。（保留对话中的！）
4. 章节字数统计与报告
"""

import os
import re
import glob

CHAPTER_DIR = "/Users/vincent/Documents/小说模型/万古神龙：我的血脉全靠吞/执行/章节"

# 说话人归属判断
SPEAKER_NAMES = set([
    "姜尘", "楚无名", "苏灵儿", "南直理", "韦煊", "威煊", "冷锋", "赵魁",
    "姜涛", "姜北望", "韩策", "管云昭", "沈霜", "顾横波",
    "铁三娘", "孟小七", "狸子", "卢岩", "何岩", "叶归鸿",
    "严鹤", "齐嫂", "白霜", "小霜", "老鬼", "袁昆",
    "陆渊", "程百谷", "月狼锋", "姬远", "姬远玄",
    "守卫", "士兵", "士卒", "府兵", "斥候", "猎手",
    "主事", "执事", "族老", "长老", "堂主", "巡察使",
    "掌柜", "老板", "老板娘", "监考", "考官",
    "老者", "老妪", "少年", "少女", "青年", "中年", "女人", "男人",
    "姜啸天", "姜蓉", "姜河",
    "守护兽", "赤蟒", "黑水幼蛟", "钢牙兽",
    "父亲", "母亲", "爷爷", "奶奶", "外公", "外婆",
])

SPEAKER_PREFIXES = set([
    "他", "她", "它", "他们", "她们", "它们", "我", "我们", "你", "你们",
    "那人", "那女人", "那男人", "对方",
    "有人",
])

def is_speaker_attribution(text):
    """判断引号后的文本是否是说话人归属说明"""
    if not text:
        return False
    
    for name in SPEAKER_NAMES:
        if text.startswith(name):
            remaining = text[len(name):]
            if not remaining or remaining[0] in '，。！？：；、……——的了着过把被将在':
                return True
            if remaining.startswith(('的', '地', '得', '和', '与', '跟')):
                return True
            if remaining and '\u4e00' <= remaining[0] <= '\u9fff':
                return True
    
    for prefix in SPEAKER_PREFIXES:
        if text.startswith(prefix):
            remaining = text[len(prefix):]
            if not remaining or remaining[0] in '，。！？：；、……——的了着过把被将在':
                return True
            if remaining and '\u4e00' <= remaining[0] <= '\u9fff':
                return True
    
    if text.startswith("声音") or text.startswith("语气") or text.startswith("话"):
        return True
    
    return False


def has_em_dash_before(text, pos):
    """检查位置前是否有破折号"""
    start = max(0, pos - 2)
    before = text[start:pos]
    return '——' in before


def optimize_dialog_narration(text):
    """优化对话与叙事的衔接"""
    result = list(text)
    closing_quote = '\u201d'
    
    i = 0
    while i < len(result):
        if result[i] == closing_quote:
            if i >= 1 and result[i-1] in '。！？':
                if i + 1 < len(result):
                    next_char = result[i+1]
                    if '\u4e00' <= next_char <= '\u9fff':
                        after_text = ''.join(result[i+1:i+15])
                        if not is_speaker_attribution(after_text):
                            if not has_em_dash_before(result, i+1):
                                result.insert(i+1, '—')
                                result.insert(i+2, '—')
                                i += 2
        i += 1
    
    return ''.join(result)


def normalize_paragraphs(text):
    """规范化段落间距"""
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def count_chinese_chars(text):
    """统计中文字符数"""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


def process_all_chapters():
    """处理所有章节文件"""
    chapter_files = sorted(glob.glob(os.path.join(CHAPTER_DIR, "第*章*.md")))
    
    total_files = len(chapter_files)
    modified_files = 0
    total_additions = 0
    
    print(f"{'='*60}")
    print(f"  万古神龙：我的血脉全靠吞 —— 章节优化报告")
    print(f"{'='*60}")
    print(f"\n找到 {total_files} 个章节文件\n")
    
    # 第一遍：优化内容
    print(f"{'─'*40}")
    print(f"  【第一阶段】内容优化")
    print(f"{'─'*40}\n")
    
    for i, filepath in enumerate(chapter_files, 1):
        filename = os.path.basename(filepath)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            original = f.read()
        
        optimized = optimize_dialog_narration(original)
        optimized = normalize_paragraphs(optimized)
        
        if original != optimized:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(optimized)
            modified_files += 1
            
            orig_dashes = original.count('——')
            opt_dashes = optimized.count('——')
            additions = opt_dashes - orig_dashes
            total_additions += additions
            
            print(f"  ✓ {filename} (新增{additions}处破折号)")
    
    print(f"\n  第一阶段完成：{modified_files}/{total_files} 个文件被修改")
    print(f"  共新增 {total_additions} 处破折号\n")
    
    # 第二遍：统计信息
    print(f"{'─'*40}")
    print(f"  【第二阶段】章节统计")
    print(f"{'─'*40}\n")
    
    total_chars = 0
    short_chapters = []
    long_chapters = []
    
    for filepath in chapter_files:
        filename = os.path.basename(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        char_count = count_chinese_chars(content)
        total_chars += char_count
        
        if char_count < 2000:
            short_chapters.append((filename, char_count))
        elif char_count > 6000:
            long_chapters.append((filename, char_count))
        
        # 段落数
        para_count = content.count('\n\n') + 1
        # 对话行数
        dialog_lines = len(re.findall(r'\u201c[^\u201d]*\u201d', content))
        
        print(f"  {filename}: {char_count}字 | {para_count}段 | {dialog_lines}处对话")
    
    avg_chars = total_chars // len(chapter_files)
    print(f"\n  总字数: {total_chars}字")
    print(f"  平均字数: {avg_chars}字/章")
    
    if short_chapters:
        print(f"\n  ⚠ 字数偏少的章节 ({len(short_chapters)}章):")
        for name, count in short_chapters:
            print(f"    - {name}: {count}字")
    
    if long_chapters:
        print(f"\n  ⚠ 字数偏多的章节 ({len(long_chapters)}章):")
        for name, count in long_chapters:
            print(f"    - {name}: {count}字")
    
    # 总结
    print(f"\n{'='*60}")
    print(f"  优化完成！")
    print(f"  修改文件: {modified_files}/{total_files}")
    print(f"  新增破折号: {total_additions}")
    print(f"  总字数: {total_chars}")
    print(f"  平均每章: {avg_chars}字")
    print(f"{'='*60}")


if __name__ == "__main__":
    # 先备份原始文件
    import shutil
    backup_dir = os.path.join(os.path.dirname(CHAPTER_DIR), "章节_备份")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        chapter_files = sorted(glob.glob(os.path.join(CHAPTER_DIR, "第*章*.md")))
        for filepath in chapter_files:
            shutil.copy2(filepath, backup_dir)
        print(f"已备份原始文件到: {backup_dir}")
    
    process_all_chapters()
