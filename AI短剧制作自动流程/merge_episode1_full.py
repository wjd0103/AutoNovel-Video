"""合并第1集 镜1~镜22 为一条完整短剧视频"""
import logging
from pathlib import Path
from moviepy import VideoFileClip, concatenate_videoclips

ROOT = Path(__file__).resolve().parent
VIDEO_DIR = ROOT / "输出" / "各集" / "第01集" / "视频"
OUTPUT_DIR = ROOT / "输出" / "各集" / "第01集"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("merge_ep1")

# 分镜信息
shot_info = [
    (1, "暴雨檐廊·苏晚等雨"),
    (2, "翻看手机·倔强无奈"),
    (3, "陆承安雨幕中出现"),
    (4, "檐廊下共伞交流"),
    (5, "「那你送我」"),
    (6, "雨中同行·伞偏向她"),
    (7, "岔路口·把伞留给你"),
    (8, "攥着伞柄目送他"),
    (9, "夜不能寐·回想"),
    (10, "操场还伞·十二圈"),
    (11, "十二个笑容"),
    (12, "「现在好了」"),
    (13, "图书馆·第一次牵手"),
    (14, "书架间·手仍握着"),
    (15, "银行卡交给你保管"),
    (16, "铁盒子的珍藏"),
    (17, "朝南阳台·看房"),
    (18, "「我们领证吧」"),
    (19, "挤在沙发聊未来"),
    (20, "「爸爸」来电"),
    (21, "手机碎裂·呆坐"),
    (22, "银杏林·雨夜空镜"),
]

print(f"\n{'═'*60}")
print("  合并第1集 镜1~镜22 → 完整短剧")
print(f"{'═'*60}\n")

clips = []
for sid, desc in shot_info:
    fp = VIDEO_DIR / f"shot_{sid:02d}.mp4"
    if not fp.is_file():
        log.error("⚠️ 文件缺失: %s", fp.name)
        continue
    clip = VideoFileClip(str(fp))
    clips.append(clip)
    log.info("  镜%02d  %s  %3.1fs", sid, desc, clip.duration)

if not clips:
    log.error("无可用视频片段")
    exit(1)

log.info("\n开始合并 %d 个片段...", len(clips))
final = concatenate_videoclips(clips, method="compose")

output_path = OUTPUT_DIR / "第01集_完整版.mp4"
final.write_videofile(
    str(output_path),
    codec="libx264",
    audio_codec="aac",
    preset="medium",
    fps=24,
    logger=None,
)

total_dur = sum(c.duration for c in clips)
total_size = output_path.stat().st_size / (1024 * 1024)

print(f"\n{'═'*60}")
print(f"  ✅ 第1集完整版合成完成")
print(f"  总时长: {total_dur:.1f}s ({total_dur/60:.1f} 分钟)")
print(f"  总大小: {total_size:.1f} MB")
print(f"  镜头数: {len(clips)}")
print(f"  输出: {output_path}")
print(f"{'═'*60}\n")

for c in clips:
    c.close()
