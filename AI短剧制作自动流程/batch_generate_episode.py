"""分镜 Batch 生成 —— 镜头分组(≤15s) + 帧连续性 + 角色参考图 + Prompt 日志

流程:
  1. 读取第 N 集的分镜 JSON
  2. ShotBatcher 分组 (每组总时长 ≤15 秒, 含多镜)
  3. 按 Batch 顺序生成视频:
     - Batch 1: 文生视频 (Text-to-Video) + 角色参考图
     - Batch 2+: 图生视频 (Image-to-Video, 起始帧=上一 Batch 的结尾帧) + 角色参考图
     - 每个 Batch 生成后提取最后一帧保存
  4. 保存 Batch Manifest + Prompt 日志
"""

from __future__ import annotations

import json
import logging
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

from 配置 import config as cfg
from 核心.frame_utils import ShotBatcher, extract_and_save_last_frame, save_batch_manifest
from 核心.音频.voice_generator import VoiceGenerator, generate_batch_voice
from 核心.音频.audio_mixer import mix_voice_to_video

# ── 配置 ──────────────────────────────────────────────────
API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"

BASE_DIR = Path(__file__).resolve().parent
CHAR_REF_DIR = BASE_DIR / "核心" / "输出" / "角色参考图"
FRAME_REF_DIR = BASE_DIR / "输出" / "帧参考图"
FRAME_REF_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("batch_episode")

# ── 角色参考图缓存 ───────────────────────────────────────
CHAR_REF_CACHE: dict[str, str] = {}


def _load_char_refs():
    for f in CHAR_REF_DIR.glob("*.jpeg") if CHAR_REF_DIR.is_dir() else []:
        name = f.stem.replace("卡通版", "").replace("版", "").strip()
        if name:
            CHAR_REF_CACHE[name] = str(f)
    for f in CHAR_REF_DIR.glob("*.png"):
        name = f.stem.replace("卡通版", "").replace("版", "").strip()
        if name:
            CHAR_REF_CACHE[name] = str(f)
    log.info("角色参考图加载: %d 张", len(CHAR_REF_CACHE))


def img_to_base64(path: Path) -> str:
    ext = path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def find_char_ref(name: str) -> Optional[str]:
    """查找角色的参考图路径"""
    for key, path in CHAR_REF_CACHE.items():
        if key in name or name in key:
            return path
    return None


# ═══════════════════════════════════════════════════════════════
# Batch 提交 & 轮询 & 帧提取
# ═══════════════════════════════════════════════════════════════


def submit_batch(
    batch: dict,
    prev_frame_path: Optional[Path],
    episode_dir: Path,
) -> dict:
    """提交一个 Batch 到 Seedance API。

    Args:
        batch: ShotBatcher 产出的 batch 字典
        prev_frame_path: 上一 Batch 的结尾帧路径 (None=文生视频)
        episode_dir: 本集输出目录

    Returns:
        {batch_id, task_id, prompt, payload, ...}
    """
    prompt = batch["prompt"]
    dur = batch["seedance_duration"]

    # ── 构建 content ──
    content: list[dict] = [{"type": "text", "text": prompt}]

    refs_used: dict[str, str] = {}

    # 上一帧作为起始图（用 reference_image 角色）
    if prev_frame_path and prev_frame_path.is_file():
        content.append({
            "type": "image_url",
            "image_url": {"url": img_to_base64(prev_frame_path)},
            "role": "reference_image",
        })
        refs_used["_prev_frame"] = str(prev_frame_path)
        log.info("  Batch%d 使用上一帧参考: %s", batch["batch_id"], prev_frame_path.name)

    # 角色参考图
    for char_name in batch.get("characters", []):
        ref_path = find_char_ref(char_name)
        if ref_path:
            content.append({
                "type": "image_url",
                "image_url": {"url": img_to_base64(Path(ref_path))},
                "role": "reference_image",
            })
            refs_used[char_name] = ref_path

    payload = {"model": MODEL, "content": content, "duration": dur, "watermark": False, "generate_audio": False}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    log.info("  Batch%d 提交: shots=%s  dur=%ds  chars=%s",
             batch["batch_id"], batch["shot_ids"], dur, batch["characters"])

    r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Batch{batch['batch_id']} 提交失败 [{r.status_code}]: {r.text[:200]}")

    task_id = r.json().get("id", "")
    return {
        "batch_id": batch["batch_id"],
        "task_id": task_id,
        "prompt": prompt,
        "payload": payload,
        "refs_used": refs_used,
        "shot_ids": batch["shot_ids"],
    }


def poll_and_download(
    sub: dict,
    episode_dir: Path,
) -> Optional[dict]:
    """轮询等待任务完成，下载视频，提取最后一帧。

    Returns:
        {batch_id, shot_ids, video_path, frame_path, prompt, ...} 或 None
    """
    bid = sub["batch_id"]
    video_dir = episode_dir / "视频"
    video_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = episode_dir / "帧参考图"
    frame_dir.mkdir(parents=True, exist_ok=True)

    url = f"{BASE_URL}/contents/generations/tasks/{sub['task_id']}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    deadline = time.time() + 600

    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            time.sleep(5)
            continue
        d = r.json()
        s = d.get("status", "")
        if s == "running":
            pass  # 继续轮询
        elif s == "succeeded":
            vu = d.get("content", {}).get("video_url", "")
            if not vu:
                log.error("  Batch%d 无 video_url", bid)
                return None

            video_path = video_dir / f"batch_{bid:02d}.mp4"
            v = requests.get(vu, timeout=120)
            video_path.write_bytes(v.content)
            size_kb = len(v.content) / 1024

            # 提取最后一帧
            frame_path = frame_dir / f"batch_{bid:02d}_last_frame.png"
            extract_and_save_last_frame(video_path, frame_path)

            log.info("  Batch%d ✅  %ds  %.0f KB  %d 镜  %s",
                     bid, sub.get("_dur", 4), size_kb,
                     len(sub["shot_ids"]), video_path.name)
            return {
                "batch_id": bid,
                "shot_ids": sub["shot_ids"],
                "video_path": video_path,
                "frame_path": frame_path if frame_path.is_file() else None,
                "prompt": sub["prompt"],
                "refs_used": sub.get("refs_used", {}),
            }

        elif s in ("failed", "cancelled", "expired"):
            err_msg = d.get("error", {}).get("message", s)
            log.error("  Batch%d ❌ %s", bid, err_msg)
            return None

        time.sleep(8)

    log.error("  Batch%d ❌ 轮询超时", bid)
    return None


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════


def generate_episode(
    episode_json_path: Path,
    episode_number: int = 1,
    dry_run: bool = False,
) -> list[dict]:
    """生成一集的 Batch 视频。

    Args:
        episode_json_path: 分镜 JSON 路径
        episode_number: 集号
        dry_run: 干跑模式

    Returns:
        batch_results list
    """
    _load_char_refs()

    episode_dir = BASE_DIR / "输出" / "各集" / f"第{episode_number:02d}集"
    episode_dir.mkdir(parents=True, exist_ok=True)

    # ── 读取分镜 ──
    storyboard = json.loads(episode_json_path.read_text(encoding="utf-8"))
    shots = storyboard.get("shots", [])
    log.info("读取 %d 个分镜", len(shots))

    if not shots:
        log.warning("无分镜数据")
        return []

    # ── ShotBatcher 分组 ──
    batcher = ShotBatcher(max_duration=15)
    batches = batcher.batch(shots)
    for i, b in enumerate(batches):
        b["batch_id"] = i + 1
    log.info("分组: %d 镜 → %d Batch", len(shots), len(batches))

    # 保存 manifest
    manifest_path = episode_dir / "batch_manifest.json"
    save_batch_manifest(batches, manifest_path)

    if dry_run:
        print(f"\n{'═'*60}")
        print(f"  [干跑] 第{episode_number}集 Batch 分组")
        print(f"{'═'*60}\n")
        for b in batches:
            print(f"  Batch{b['batch_id']:02d}: 镜{b['shot_ids']}  "
                  f"总{b['total_duration']:.0f}s → API {b['seedance_duration']}s  "
                  f"角色:{b['characters']}")
        print(f"\n  Manifest: {manifest_path}\n")
        return []

    # ── 逐 Batch 生成（串行，依赖上一帧）──
    print(f"\n{'═'*60}")
    print(f"  第{episode_number}集 Batch 视频生成  ({len(batches)} batches)")
    print(f"{'═'*60}\n")

    # 建立 shot_id → shot_data 映射
    shot_map = {s["id"]: s for s in shots}

    t_start = time.perf_counter()
    prev_frame: Optional[Path] = None
    results: list[dict] = []

    for batch in batches:
        bid = batch["batch_id"]

        # 提交 Seedance（无音频）
        sub = submit_batch(batch, prev_frame, episode_dir)
        sub["_dur"] = batch["seedance_duration"]

        # 轮询
        result = poll_and_download(sub, episode_dir)
        if result:
            results.append(result)
            print(f"  ✅ Batch{bid:02d} 视频: 镜{result['shot_ids']}  →  {result['video_path'].name}")

            # ── TTS 配音生成 ──
            batch_shots = [shot_map[sid] for sid in batch["shot_ids"] if sid in shot_map]
            audio_path = generate_batch_voice(
                batch_shots,
                batch_id=bid,
                episode_number=episode_number,
            )
            if audio_path:
                print(f"     TTS: {audio_path.name}")

            # ── 合成视频+配音 ──
            video_path = result["video_path"]
            final_dir = episode_dir / "最终视频"
            final_path = mix_voice_to_video(video_path, audio_path, final_dir / video_path.name)
            if final_path:
                print(f"     🎬 合成: {final_path.name}")
            elif audio_path is None:
                print(f"     无配音，使用无声视频")

            # 更新上一帧参考
            if result.get("frame_path"):
                prev_frame = result["frame_path"]
        else:
            print(f"  ❌ Batch{bid:02d}: 视频生成失败，停止后续 batches")
            break

    elapsed = time.perf_counter() - t_start

    # ── 汇总 ──
    print(f"\n{'═'*60}")
    print(f"  ✅ 第{episode_number}集 Batch 生成完成")
    total_videos = len(results)
    total_shots_generated = sum(r["shot_count"] for r in results) if results else 0
    print(f"  视频数: {total_videos}/{len(batches)}  |  耗时: {elapsed:.0f}s")
    print(f"  包含镜头: {sum(len(r['shot_ids']) for r in results)} 个")
    print(f"  配音: TTS (edge-tts)  |  音频模式: 独立生成+合成")
    print(f"{'═'*60}\n")

    for r in sorted(results, key=lambda x: x["batch_id"]):
        final_video = episode_dir / "最终视频" / f"batch_{r['batch_id']:02d}.mp4"
        if final_video.is_file():
            size = final_video.stat().st_size / (1024 * 1024)
            print(f"  🎬 Batch{r['batch_id']:02d}: 镜{r['shot_ids']}  →  最终视频/{final_video.name}  ({size:.1f} MB)")
        else:
            print(f"  ✅ Batch{r['batch_id']:02d}: 镜{r['shot_ids']}  →  {r['video_path'].name}")

    # ── 保存 Prompt 日志 ──
    prompt_log = []
    log_path = episode_dir / "seedance_prompt_log.json"
    if log_path.is_file():
        prompt_log = json.loads(log_path.read_text(encoding="utf-8"))
    for r in results:
        prompt_log.append({
            "batch_id": r["batch_id"],
            "shot_ids": r["shot_ids"],
            "episode": episode_number,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": r["prompt"],
            "character_references": r.get("refs_used", {}),
            "model": MODEL,
        })
    log_path.write_text(json.dumps(prompt_log, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Prompt 日志已保存: %s  (%d 条)", log_path.name, len(prompt_log))

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="分镜 Batch 生成")
    parser.add_argument("--episode", type=int, default=1, help="集号")
    parser.add_argument("--dry-run", action="store_true", help="干跑模式")
    args = parser.parse_args()

    ep_dir = BASE_DIR / "输出" / "各集" / f"第{args.episode:02d}集"
    json_path = ep_dir / "分镜.json"

    if not json_path.is_file():
        log.error("分镜文件不存在: %s", json_path)
        exit(1)

    generate_episode(json_path, episode_number=args.episode, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
