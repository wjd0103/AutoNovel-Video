"""
按分镜要求时长圆整到 API 支持的固定值，重新生成镜1(4s)、镜3(3s→4s)、镜4(4s)
Seedance Fast 支持时长: 4, 5, 6, 8, 10, 12 秒
"""
import logging, time, requests
from pathlib import Path

from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"
OUT_DIR = Path(__file__).resolve().parent / "输出" / "各集" / "第01集" / "视频"
OUT_DIR.mkdir(parents=True, exist_ok=True)

VALID_DURS = [4, 5, 6, 8, 10, 12]

def round_duration(requested: float) -> int:
    """圆整到最近的 API 支持时长"""
    return min(VALID_DURS, key=lambda x: abs(x - requested))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("duration")

# (shot_id, prompt, requested_duration)
shots = [
    (1, "暴雨如注的傍晚，老旧教学楼外，雨水顺着屋檐倾泻而下，地面湿漉漉反射昏黄灯光。一个年轻女生独自站在檐廊下，背着画筒，望着雨幕发呆。电影感画面，暖色调。", 4),
    (3, "雨幕边缘，一个高大男生穿着深灰色卫衣出现，头发微湿，手里举着一把折叠伞，眼睛很亮，看向前方。近景。", 3),
    (4, "大雨中，一个年轻女生和打伞的男生站在教学楼檐廊下避雨聊天，男生把伞往女生那边倾斜。中景，温暖细腻电影光感。", 4),
]


def submit(prompt, dur):
    payload = {"model": MODEL, "content": [{"type": "text", "text": prompt}], "duration": dur, "watermark": False}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"提交失败 [{r.status_code}]: {r.text[:200]}")
    return r.json().get("id", "")


def poll_download(task_id, sid, actual_dur):
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
            log.info("镜%02d ✅ 请求%ds→实际%ds  %.0f KB", sid, actual_dur, len(v.content)/1024)
            return p
        elif s in ("failed", "cancelled", "expired"):
            raise RuntimeError(d.get("error", {}).get("message", s))
        time.sleep(5)
    raise RuntimeError("超时")


def main():
    print(f"\n按分镜要求时长（圆整到API支持的固定值）重新生成:\n")

    tasks = []
    for sid, prompt, req_dur in shots:
        actual_dur = round_duration(req_dur)
        note = f" (原{req_dur}s→圆整)" if actual_dur != req_dur else ""
        tid = submit(prompt, actual_dur)
        tasks.append((sid, tid, actual_dur, req_dur))
        log.info("镜%02d  请求%ds→实际%ds%s  task_id=%s", sid, req_dur, actual_dur, note, tid)

    print("\n轮询中...\n")
    ok = 0
    for sid, tid, actual_dur, req_dur in tasks:
        try:
            poll_download(tid, sid, actual_dur)
            ok += 1
        except Exception as e:
            log.error("镜%02d ❌ %s", sid, e)

    print(f"\n{'═'*50}")
    print(f"  成功: {ok}/{len(tasks)}")
    print(f"  输出: {OUT_DIR}\n")
    print(f"  说明: Seedance Fast API 仅支持固定时长 {VALID_DURS} 秒")
    print(f"        分镜要求的 3s → 圆整到 4s，4s → 4s，5s → 5s\n")


if __name__ == "__main__":
    main()
