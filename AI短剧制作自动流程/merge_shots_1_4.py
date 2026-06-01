"""将第1集前4个镜头视频合并为一个完整片段"""
import logging
from pathlib import Path

from moviepy import VideoFileClip, concatenate_videoclips

ROOT = Path(__file__).resolve().parent
VIDEO_DIR = ROOT / "输出" / "各集" / "第01集" / "视频"
OUTPUT_DIR = ROOT / "输出" / "各集" / "第01集"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("merge")

shot_files = [
    VIDEO_DIR / "shot_01.mp4",
    VIDEO_DIR / "shot_02.mp4",
    VIDEO_DIR / "shot_03.mp4",
    VIDEO_DIR / "shot_04.mp4",
]

# 分镜信息（用于日志）
shot_info = [
    ("镜1", 4, "暴雨檐廊·苏晚等雨"),
    ("镜2", 5, "翻看手机·倔强无奈"),
    ("镜3", 4, "陆承安雨幕中出现"),
    ("镜4", 4, "檐廊下共伞交流"),
]

print(f"\n{'═'*50}")
print("  合并第1集 镜1~镜4")
print(f"{'═'*50}\n")

clips = []
for i, (fp, (name, dur, desc)) in enumerate(zip(shot_files, shot_info)):
    if not fp.is_file():
        log.error("文件不存在: %s", fp.name)
        continue
    clip = VideoFileClip(str(fp))
    clips.append(clip)
    log.info("  %s  %s  %ds  %.0f KB", name, desc, clip.duration, fp.stat().st_size / 1024)

if not clips:
    log.error("没有可用的视频片段")
    exit(1)

log.info("\n开始合并 %d 个片段...", len(clips))

final = concatenate_videoclips(clips, method="compose")
output_path = OUTPUT_DIR / "第01集_镜1-4_合并版.mp4"
final.write_videofile(
    str(output_path),
    codec="libx264",
    audio_codec="aac",
    preset="medium",
    fps=24,
    logger=None,
)

total_dur = sum(c.duration for c in clips)
final_size = output_path.stat().st_size / (1024 * 1024)

print(f"\n{'═'*50}")
print(f"  ✅ 合并完成")
print(f"  总时长: {total_dur:.1f}s")
print(f"  文件大小: {final_size:.1f} MB")
print(f"  输出: {output_path}")
print(f"{'═'*50}\n")

for c in clips:
    c.close()
