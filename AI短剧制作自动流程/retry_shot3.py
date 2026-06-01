"""重试镜3 — 纯场景描述避免版权"""
import logging, time, requests
from pathlib import Path
from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"
OUT_DIR = Path(__file__).resolve().parent / "输出" / "各集" / "第01集" / "视频"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("shot3")

prompt = "雨夜大学校园，一个年轻男生的身影从雨幕中走出来，穿着灰色卫衣头发微湿，手里拿着一把折叠伞。电影感画面。"
sid, dur = 3, 4

payload = {"model": MODEL, "content": [{"type": "text", "text": prompt}], "duration": dur, "watermark": False}
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
tid = r.json().get("id", "")
log.info("镜%02d  %ds  task_id=%s", sid, dur, tid)

url = f"{BASE_URL}/contents/generations/tasks/{tid}"
deadline = time.time() + 300
while time.time() < deadline:
    r = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
    if r.status_code != 200:
        time.sleep(5); continue
    d = r.json(); s = d.get("status", "")
    if s == "succeeded":
        vu = d.get("content", {}).get("video_url", "")
        if vu:
            p = OUT_DIR / f"shot_{sid:02d}.mp4"
            v = requests.get(vu, timeout=120)
            p.write_bytes(v.content)
            log.info("镜%02d ✅ %ds  %.0f KB", sid, dur, len(v.content)/1024)
            break
    elif s in ("failed", "cancelled", "expired"):
        log.error("镜%02d ❌ %s", sid, d.get("error", {}).get("message", s))
        break
    time.sleep(5)
