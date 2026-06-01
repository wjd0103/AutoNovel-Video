"""
重试 镜3 和 镜4 — 简化 Prompt 避免角色名触发版权过滤
"""
import json, logging, time, requests
from pathlib import Path

from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"
OUT_DIR = Path(__file__).resolve().parent / "输出" / "各集" / "第01集" / "视频"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("retry")

shots = [
    {"shot_id": 3, "prompt": "雨幕边缘，一个高大男生穿着深灰色卫衣出现，头发微湿，手里举着一把折叠伞，眼睛很亮，看向镜头方向。电影感画面，暖色调。", "dur": 5},
    {"shot_id": 4, "prompt": "大雨中，一个年轻女生和打伞的男生站在教学楼的檐廊下避雨，男生把伞往女生那边倾斜，自己半边肩膀淋在雨里。近景，温暖细腻，电影光感。", "dur": 5},
]


def submit(prompt, dur):
    payload = {"model": MODEL, "content": [{"type": "text", "text": prompt}], "duration": dur, "watermark": False}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"提交失败 [{r.status_code}]: {r.text[:200]}")
    return r.json().get("id", "")


def poll_download(task_id, sid):
    url = f"{BASE_URL}/contents/generations/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    deadline = time.time() + 300
    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            time.sleep(5); continue
        d = r.json()
        s = d.get("status", "")
        if s == "succeeded":
            video_url = d.get("content", {}).get("video_url", "")
            if not video_url:
                raise RuntimeError("无 video_url")
            p = OUT_DIR / f"shot_{sid:02d}.mp4"
            v = requests.get(video_url, timeout=120)
            p.write_bytes(v.content)
            log.info("镜%02d ✅ 下载完成  %.0f KB", sid, len(v.content)/1024)
            return p
        elif s in ("failed", "cancelled", "expired"):
            raise RuntimeError(d.get("error", {}).get("message", s))
        time.sleep(5)
    raise RuntimeError("超时")


def main():
    tasks = []
    for s in shots:
        tid = submit(s["prompt"], s["dur"])
        tasks.append((s["shot_id"], tid))
        log.info("镜%02d 提交成功  task_id=%s", s["shot_id"], tid)

    print("\n轮询中...\n")
    for sid, tid in tasks:
        try:
            p = poll_download(tid, sid)
            log.info("镜%02d ✅ %s", sid, p.name)
        except Exception as e:
            log.error("镜%02d ❌ %s", sid, e)

    print(f"\n输出目录: {OUT_DIR}\n")


if __name__ == "__main__":
    main()
