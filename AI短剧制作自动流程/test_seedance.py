"""
Seedance 2.0 Fast 文生视频测试脚本
调用火山引擎 Ark API 将第1集第1镜的文本描述转为短视频
"""

import json
import logging
import sys
import time
from pathlib import Path

import requests

# ── 配置 ──────────────────────────────────────────────────
from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = (cfg.IMAGE_API_BASE_URL).rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"  # Fast 版

OUTPUT_DIR = Path(__file__).resolve().parent / "输出" / "测试视频"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("seedance_test")


def submit_task(prompt: str, duration: int = 5) -> str:
    """提交文生视频任务，返回 task_id"""
    url = f"{BASE_URL}/contents/generations/tasks"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "content": [
            {"type": "text", "text": prompt}
        ],
        "duration": duration,
        "watermark": False,
    }

    log.info("提交文生视频任务...")
    log.info("模型: %s  时长: %ds", MODEL, duration)
    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if resp.status_code != 200:
        log.error("提交失败 [%d]: %s", resp.status_code, resp.text[:300])
        sys.exit(1)

    data = resp.json()
    task_id = data.get("id", "")
    if not task_id:
        log.error("未返回 task_id: %s", resp.text[:200])
        sys.exit(1)

    log.info("任务已提交  task_id=%s", task_id)
    return task_id


def poll_task(task_id: str, timeout: int = 300, interval: float = 5.0) -> dict:
    """轮询任务状态直到完成或超时"""
    url = f"{BASE_URL}/contents/generations/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {API_KEY}"}

    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            log.warning("查询失败 [%d]，重试...", resp.status_code)
            time.sleep(interval)
            continue

        data = resp.json()
        status = data.get("status", "")
        log.info("状态: %s", status)

        if status == "succeeded":
            video_url = data.get("content", {}).get("video_url", "")
            if video_url:
                log.info("视频生成成功!")
                return {"video_url": video_url, "data": data}
            log.error("状态 succeeded 但无 video_url")
            return {"video_url": "", "data": data}

        elif status in ("failed", "cancelled", "expired"):
            err = data.get("error", {})
            log.error("任务失败: %s", err.get("message", status))
            return {"video_url": "", "data": data, "error": err}

        time.sleep(interval)

    log.error("轮询超时 (%ds)", timeout)
    return {"video_url": "", "data": {}, "error": "timeout"}


def download_video(video_url: str, output_path: Path) -> Path:
    """下载视频到本地"""
    log.info("正在下载视频...")
    resp = requests.get(video_url, timeout=120)
    if resp.status_code != 200:
        log.error("下载失败 [%d]", resp.status_code)
        sys.exit(1)
    output_path.write_bytes(resp.content)
    size_mb = len(resp.content) / (1024 * 1024)
    log.info("下载完成  %s  (%.1f MB)", output_path.name, size_mb)
    return output_path


def main():
    # ── 第1集第1镜的 Prompt ──
    prompt = (
        "暴雨如注的傍晚，建筑系老旧教学楼外，雨水顺着屋檐倾泻而下，"
        "地面湿漉漉反射昏黄灯光。一个年轻女生独自站在檐廊下，"
        "背着画筒，衣服微湿，望着雨幕发呆。"
        "wide shot, cinematic lighting, 怀旧温暖色调"
    )

    print("\n" + "═" * 50)
    print("  Seedance 2.0 Fast 文生视频测试")
    print("═" * 50 + "\n")
    print(f"Prompt: {prompt}\n")

    # 提交任务
    task_id = submit_task(prompt, duration=4)

    # 轮询
    result = poll_task(task_id)

    if result.get("video_url"):
        out_path = OUTPUT_DIR / "shot_01_test.mp4"
        download_video(result["video_url"], out_path)
        print(f"\n✅ 测试完成  视频已保存: {out_path}")
    else:
        print(f"\n❌ 视频生成失败: {result.get('error', '未知错误')}")
        if result.get("data"):
            print(f"返回数据: {json.dumps(result['data'], ensure_ascii=False, indent=2)[:500]}")


if __name__ == "__main__":
    main()
