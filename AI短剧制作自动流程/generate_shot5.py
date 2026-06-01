"""用苏晚角色参考图 + Seedance 生成第1集镜5视频"""
import logging, time, requests, base64
from pathlib import Path

from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"
VALID_DURS = [4, 5, 6, 8, 10, 12]

BASE_DIR = Path(__file__).resolve().parent

OUT_DIR = BASE_DIR / "输出" / "各集" / "第01集" / "视频"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("shot5")

# ── 角色参考图 ──
SU_WAN_REF = BASE_DIR / "核心" / "输出" / "角色参考图" / "卡通版苏晚.jpeg"
LU_CHENG_AN_REF = BASE_DIR / "核心" / "输出" / "角色参考图" / "陆承安卡通版.jpeg"

def img_to_base64(path: Path) -> str:
    ext = path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def round_dur(d):
    return min(VALID_DURS, key=lambda x: abs(x - d))

# ── 镜5 Prompt（基于分镜描述）──
prompt = (
    "近景，大学教学楼檐廊下，一个黑长直发的年轻女生犹豫了两秒，眼神从犹豫变得坚定，"
    "她抬头直视面前的高大男生。男生愣了一下，随即露出温暖笑容，眼睛弯成月牙。"
    "两人在昏黄灯光下对视，雨幕背景，温暖电影感画面。"
)

# ── 构建 content 数组（文本 + 角色参考图）──
content = [{"type": "text", "text": prompt}]

# 添加苏晚参考图
if SU_WAN_REF.is_file():
    content.append({"type": "image_url", "image_url": {"url": img_to_base64(SU_WAN_REF)}, "role": "reference_image"})
    log.info("苏晚参考图: %s  (%.0f KB)", SU_WAN_REF.name, SU_WAN_REF.stat().st_size / 1024)
else:
    log.warning("苏晚参考图不存在: %s", SU_WAN_REF)

# 添加陆承安参考图
if LU_CHENG_AN_REF.is_file():
    content.append({"type": "image_url", "image_url": {"url": img_to_base64(LU_CHENG_AN_REF)}, "role": "reference_image"})
    log.info("陆承安参考图: %s  (%.0f KB)", LU_CHENG_AN_REF.name, LU_CHENG_AN_REF.stat().st_size / 1024)
else:
    log.warning("陆承安参考图不存在: %s", LU_CHENG_AN_REF)

duration = round_dur(4)

print(f"\n{'═'*50}")
print("  生成第1集 镜5 — 苏晚+陆承安参考图")
print(f"{'═'*50}\n")
print(f"  Prompt: {prompt[:80]}...")
print(f"  时长: {duration}s")
print(f"  苏晚参考图路径: {SU_WAN_REF}")
print(f"  陆承安参考图路径: {LU_CHENG_AN_REF}\n")

# ── 提交任务 ──
payload = {"model": MODEL, "content": content, "duration": duration, "watermark": False}
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

log.info("提交 Seedance 任务...")
r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
if r.status_code != 200:
    log.error("提交失败 [%d]: %s", r.status_code, r.text[:300])
    exit(1)

task_id = r.json().get("id", "")
log.info("task_id=%s", task_id)

# ── 轮询 ──
url = f"{BASE_URL}/contents/generations/tasks/{task_id}"
deadline = time.time() + 300
while time.time() < deadline:
    r = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
    if r.status_code != 200:
        time.sleep(5); continue
    d = r.json(); s = d.get("status", "")
    if s == "running":
        log.info("  生成中...")
    elif s == "succeeded":
        vu = d.get("content", {}).get("video_url", "")
        if vu:
            out_path = OUT_DIR / "shot_05.mp4"
            v = requests.get(vu, timeout=120)
            out_path.write_bytes(v.content)
            log.info("✅ 镜5 下载完成  %.0f KB", len(v.content)/1024)
            print(f"\n  ✅ 视频已保存: {out_path}\n")
            break
    elif s in ("failed", "cancelled", "expired"):
        log.error("❌ 失败: %s", d.get("error", {}).get("message", s))
        break
    time.sleep(6)
