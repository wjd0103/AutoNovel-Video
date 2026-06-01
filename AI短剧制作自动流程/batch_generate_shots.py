"""
批量生成第1集 镜1~镜4 视频
并发提交 Seedance Fast API，轮询等待，下载到 输出/各集/第01集/视频/
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"

PROJECT_ROOT = Path(__file__).resolve().parent

SHOTS_JSON = PROJECT_ROOT / "输出" / "各集" / "第01集" / "视频Prompt.json"
OUT_DIR = PROJECT_ROOT / "输出" / "各集" / "第01集" / "视频"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("batch")


def load_shots(shot_ids: list[int]) -> list[dict]:
    all_shots = json.loads(SHOTS_JSON.read_text(encoding="utf-8"))
    return [s for s in all_shots if s["shot_id"] in shot_ids]


def submit(shot: dict) -> dict:
    prompt = shot["image_prompt"]
    dur = max(2, min(8, int(shot["duration"])))
    payload = {"model": MODEL, "content": [{"type": "text", "text": prompt}], "duration": dur, "watermark": False}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"提交失败 [{resp.status_code}]: {resp.text[:200]}")
    task_id = resp.json().get("id", "")
    log.info("镜%02d 提交成功  task_id=%s", shot["shot_id"], task_id)
    return {"shot": shot, "task_id": task_id}


def poll_and_download(result: dict) -> dict:
    shot = result["shot"]
    task_id = result["task_id"]
    sid = shot["shot_id"]
    url = f"{BASE_URL}/contents/generations/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    deadline = time.time() + 300

    while time.time() < deadline:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            time.sleep(5)
            continue
        data = resp.json()
        status = data.get("status", "")
        if status == "succeeded":
            video_url = data.get("content", {}).get("video_url", "")
            if not video_url:
                raise RuntimeError("succeeded 但无 video_url")
            out_path = OUT_DIR / f"shot_{sid:02d}.mp4"
            vresp = requests.get(video_url, timeout=120)
            out_path.write_bytes(vresp.content)
            size = len(vresp.content) / 1024
            log.info("镜%02d ✅ 下载完成  %s  (%.0f KB)", sid, out_path.name, size)
            return {"shot": shot, "path": out_path, "size_kb": size}
        elif status in ("failed", "cancelled", "expired"):
            err = data.get("error", {}).get("message", status)
            raise RuntimeError(f"任务失败: {err}")
        time.sleep(5)

    raise RuntimeError("轮询超时")


def main():
    shots = load_shots([1, 2, 3, 4])
    print(f"\n开始生成 {len(shots)} 个镜头视频...\n")

    t0 = time.perf_counter()
    submitted = []

    with ThreadPoolExecutor(max_workers=4) as exc:
        fs = [exc.submit(submit, s) for s in shots]
        for f in as_completed(fs):
            submitted.append(f.result())

    log.info("全部任务已提交，开始轮询...")

    results = []
    with ThreadPoolExecutor(max_workers=4) as exc:
        fs = [exc.submit(poll_and_download, r) for r in submitted]
        for f in as_completed(fs):
            try:
                results.append(f.result())
            except Exception as e:
                log.error("  ❌ %s", e)

    elapsed = time.perf_counter() - t0
    results.sort(key=lambda r: r["shot"]["shot_id"])
    print(f"\n{'═'*50}")
    for r in results:
        s = r["shot"]
        print(f"  镜{s['shot_id']:02d}  {s['duration']}s  →  {r['path'].name}")
    print(f"{'═'*50}")
    print(f"  成功: {len(results)}/{len(shots)}  |  耗时: {elapsed:.0f}s")
    print(f"  输出: {OUT_DIR.resolve()}\n")


if __name__ == "__main__":
    main()
