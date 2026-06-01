"""重新生成第2集分镜 + 生成前2个 Batch 视频"""
import json, logging, sys, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
NOVEL_PATH = BASE_DIR / "测试" / "银杏叶落时"
SCRIPT_PATH = BASE_DIR / "输出" / "剧本" / "银杏叶落时_全剧剧本.json"
EP_DIR = BASE_DIR / "输出" / "各集" / "第02集"
EP_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ep2_gen")

# ── 1. 读取小说，提取第2节 ──
novel_text = NOVEL_PATH.read_text(encoding="utf-8")
# 小说以 "一" "二" "三" 等分节（单独一行）
import re
markers = [(m.start(), m.group()) for m in re.finditer(r'^[一二三四五六七八九十十一十二]+$', novel_text, re.MULTILINE)]
ep2_start, ep2_end = None, None
for i, (pos, marker) in enumerate(markers):
    if marker == "二":
        ep2_start = pos + len(marker) + 1  # 跳过 "二\n"
        ep2_end = markers[i+1][0] if i+1 < len(markers) else len(novel_text)
        break

if ep2_start is None:
    log.error("未找到第2节")
    sys.exit(1)

ep2_text = novel_text[ep2_start:ep2_end].strip()

log.info("第2节文本长度: %d 字符", len(ep2_text))

# ── 2. 读取全剧设定 ──
script_data = json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))
settings_json = json.dumps(script_data["settings"], ensure_ascii=False, indent=2)

# ── 3. 调用 ShotStoryboardAgent 生成分镜 ──
log.info("开始生成第2集分镜...")
from 核心.storyboard_agent import ShotStoryboardAgent, EpisodeStoryboard
from 核心.剧本.script_parser import save_episode_storyboard

agent = ShotStoryboardAgent()
t0 = time.perf_counter()
storyboard = agent.run(
    ep2_text.strip(),
    episode_number=2,
    episode_title="十二个笑容",
    series_setting=settings_json,
)
elapsed = time.perf_counter() - t0
log.info("生成 %d 个分镜 | 耗时 %.1fs", len(storyboard.shots), elapsed)

json_path, md_path = save_episode_storyboard(storyboard)
log.info("分镜已保存: %s", md_path.name)

# ── 4. 生成视频 Prompt ──
from 核心.prompt_generator import PromptGenerator
from 核心.asset_library import AssetLibrary
from 核心.剧本.script_models import SCRIPT_DIR as SCRIPT_OUT_DIR

asset_path = SCRIPT_OUT_DIR / "银杏叶落时_视觉资产库.json"
asset_library = None
if asset_path.is_file():
    asset_library = AssetLibrary.load(asset_path)
    log.info("已加载视觉资产库")

generator = PromptGenerator(
    visual_style=script_data["settings"]["visual_style"],
    asset_library=asset_library,
)

plans = generator.generate_episode_plans(storyboard)
prompt_path = EP_DIR / "视频Prompt.json"
prompt_path.write_text(
    json.dumps([p.model_dump() for p in plans], ensure_ascii=False, indent=2),
    encoding="utf-8",
)
log.info("视频Prompt已保存: %d 个镜头", len(plans))

print(f"\n{'═'*60}")
print(f"  第2集「十二个笑容」- {len(storyboard.shots)} 个分镜")
print(f"{'═'*60}\n")
for s in storyboard.shots[:6]:
    print(f"  镜{s.id:02d}  {s.shot_type}  {s.duration}s  chars={s.character_list}")
if len(storyboard.shots) > 6:
    print(f"  ... 共 {len(storyboard.shots)} 镜")
print()

# ── 5. 用 batch_generate_episode 生成前2个 Batch ──
print("即将开始视频生成...")
print("  模型: doubao-seedance-2-0-fast-260128")
print("  方式: Batch分组(≤15s) + 帧连续性 + 角色参考图")
print()

# 只生成前2个 batch: 修改 batch_generate_episode 的 max_batches
from 核心.frame_utils import ShotBatcher, extract_and_save_last_frame
from batch_generate_episode import submit_batch, poll_and_download, _load_char_refs

_load_char_refs()

batcher = ShotBatcher(max_duration=15)
# 用分镜数据构造 shots list
shots_data = []
for s in storyboard.shots:
    shots_data.append({
        "id": s.id,
        "duration": s.duration,
        "scene_content": s.scene_content,
        "camera_movement": s.camera_movement,
        "shot_type": s.shot_type,
        "character_list": s.character_list,
        "audio_content": s.audio_content,
        "notes": s.notes,
    })

batches = batcher.batch(shots_data)
for i, b in enumerate(batches):
    b["batch_id"] = i + 1

log.info("分组: %d 镜 → %d Batch", len(shots_data), len(batches))

# 只生成前2个
max_batches = min(2, len(batches))
prev_frame = None
results = []

for batch in batches[:max_batches]:
    bid = batch["batch_id"]
    log.info("Batch%d 开始: 镜%s  %ds", bid, batch["shot_ids"], batch["seedance_duration"])
    
    sub = submit_batch(batch, prev_frame, EP_DIR)
    sub["_dur"] = batch["seedance_duration"]
    
    result = poll_and_download(sub, EP_DIR)
    if result:
        results.append(result)
        if result.get("frame_path"):
            prev_frame = result["frame_path"]
        print(f"  ✅ Batch{bid:02d}: 镜{result['shot_ids']}  →  {result['video_path'].name}")
    else:
        print(f"  ❌ Batch{bid:02d}: 失败")
        break

# ── 汇总 ──
total_elapsed = time.perf_counter() - t0
print(f"\n{'═'*60}")
print(f"  第2集 前{len(results)}个 Batch 生成完成")
for r in results:
    shot_ids = r["shot_ids"]
    total_dur = sum(s.duration for s in storyboard.shots if s.id in shot_ids)
    print(f"  ✅ Batch{r['batch_id']:02d}: 镜{shot_ids}  ({total_dur:.0f}s)  →  {r['video_path'].name}")
print(f"{'═'*60}\n")
