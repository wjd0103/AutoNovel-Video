"""视频生成模块 — Seedance 图生视频 API 封装

将 Seedream 生成的静态图片转化为 2-5 秒的短视频片段，
使用豆包 Seedance 2.0 的 image-to-video 能力。

API 模式: 异步任务（提交 → 轮询 → 下载 mp4）
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from config import config as cfg

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = PROJECT_ROOT / "output" / "images"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
VIDEO_DIR = PROJECT_ROOT / "output" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class VideoTask:
    scene_id: int
    task_id: str | None = None
    status: str = "pending"
    video_url: str = ""
    output_path: Path | None = None
    elapsed: float = 0.0
    error: str = ""


@dataclass
class VideoBatchResult:
    tasks: list[VideoTask] = field(default_factory=list)
    total_elapsed: float = 0.0

    @property
    def ok(self) -> int:
        return sum(1 for t in self.tasks if t.status == "completed")


# ═══════════════════════════════════════════════════════════════
# Seedance 视频生成器
# ═══════════════════════════════════════════════════════════════


class SeedanceGenerator:
    """将静态图片转化为短视频片段。

    用法::

        gen = SeedanceGenerator()
        result = gen.generate_clips(image_paths, durations, prompts)
        # → output/videos/scene_01.mp4 ...
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        poll_interval: Optional[float] = None,
        poll_timeout: Optional[int] = None,
        max_workers: int = 4,
    ) -> None:
        self._model = model or cfg.VIDEO_MODEL
        self._api_key = api_key or cfg.IMAGE_API_KEY
        self._base_url = (base_url or cfg.IMAGE_API_BASE_URL).rstrip("/")
        self._poll_interval = poll_interval or cfg.VIDEO_POLL_INTERVAL
        self._poll_timeout = poll_timeout or cfg.VIDEO_POLL_TIMEOUT
        self._max_workers = max_workers

        if not self._api_key:
            raise RuntimeError("API Key 未设置 (需要 IMAGE_API_KEY 用于 Seedance)")

        logger.info(
            "SeedanceGenerator 初始化  model=%s  poll=%.0fs  timeout=%ds",
            self._model, self._poll_interval, self._poll_timeout,
        )

    # ── 公开入口 ─────────────────────────────────────────────

    def generate_clips(
        self,
        image_paths: list[Path],
        durations: list[float],
        prompts: list[str],
        scene_ids: Optional[list[int]] = None,
    ) -> VideoBatchResult:
        """批量生成视频片段。

        Args:
            image_paths: 每镜的源图片路径
            durations: 每镜的目标视频时长（秒，对齐配音长度）
            prompts: 每镜的运动描述 prompt（中文）
            scene_ids: 分镜 ID 列表（可选）

        Returns:
            VideoBatchResult
        """
        n = len(image_paths)
        if n == 0:
            return VideoBatchResult(total_elapsed=0)
        if scene_ids is None:
            scene_ids = list(range(1, n + 1))

        t_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("开始 Seedance 视频生成  分镜数=%d  model=%s", n, self._model)

        # ── 阶段一: 并行提交所有任务 ──────────────────────────
        tasks: list[VideoTask] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures: dict = {}
            for i in range(n):
                dur = max(1.0, min(15.0, durations[i]))
                f = executor.submit(
                    self._submit_task,
                    image_paths[i], dur, prompts[i], scene_ids[i],
                )
                futures[f] = i

            for f in as_completed(futures):
                i = futures[f]
                try:
                    task = f.result()
                except Exception as exc:
                    task = VideoTask(scene_id=scene_ids[i], status="submit_failed", error=str(exc))
                tasks.append(task)
                marker = "✅" if task.task_id else "❌"
                logger.info(
                    "  [提交] %s scene_%02d  task=%s",
                    marker, task.scene_id,
                    task.task_id or task.error[:60],
                )

        # ── 阶段二: 轮询等待所有任务完成 ──────────────────────
        tasks.sort(key=lambda t: t.scene_id)
        pending = [t for t in tasks if t.task_id and t.status not in ("completed", "failed")]

        if pending:
            logger.info("  开始轮询 %d 个任务…", len(pending))
            self._poll_all(pending)

        total_elapsed = time.perf_counter() - t_start
        result = VideoBatchResult(tasks=tasks, total_elapsed=total_elapsed)

        ok = result.ok
        logger.info(
            "Seedance 视频生成完成  %d/%d  总耗时 %.0fs",
            ok, n, total_elapsed,
        )
        return result

    # ── 任务提交 ─────────────────────────────────────────────

    def _submit_task(
        self, image_path: Path, duration: float, prompt: str, scene_id: int,
    ) -> VideoTask:
        t0 = time.perf_counter()

        payload: dict = {
            "model": self._model,
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                },
                {
                    "type": "image_url",
                    "image_url": {"url": self._upload_image(image_path)},
                uests.post(
              "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Seedance 提交失败 {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        task_id = data.get("id", "")
        if not task_id:
            raise RuntimeError("未返回 task id")

        return VideoTask(
            scene_id=scene_id,
            task_id=task_id,
            status="submitted",
            elapsed=time.perf_counter() - t0,
        )

    # ── 图片上传 ─────────────────────────────────────────────

    def _upload_image(self, image_path: Path) -> str:
        """将本地图片上传为临时 URL（用于 Seedance 图生视频）。

        先尝试直接用 file:// 如果 API 支持；否则用临时可访问 URL。
        Seedance API 要求 image_url 是一个可公网访问的 URL。
        """
        if not image_path.is_file():
            raise FileNotFoundError(f"图片不存在: {image_path}")

        import base64

        ext = image_path.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/png")

        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    # ── 轮询 ─────────────────────────────────────────────────

    def _poll_all(self, tasks: list[VideoTask]) -> None:
        deadline = time.perf_counter() + self._poll_timeout

        while time.perf_counter() < deadline:
            pending = [t for t in tasks if t.status not in ("completed", "failed")]
            if not pending:
                return

            for t in pending:
                try:
                    resp = requests.get(
                        f"{self._base_url}/contents/generations/tasks/{t.task_id}",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    status = data.get("status", "")
                    t.status = status

                    if status == "succeeded":
                        t.video_url = data.get("content", {}).get("video_url", "")
                        if not t.video_url:
                            t.status = "failed"
                            t.error = "任务成功但无 video_url"
                        else:
                            t.output_path = VIDEO_DIR / f"scene_{t.scene_id:02d}.mp4"
                            self._download_video(t)
                            t.status = "completed"
                    elif status in ("failed", "cancelled", "expired"):
                        err = data.get("error", {})
                        t.error = err.get("message", status)
                except Exception as exc:
                    logger.debug("  轮询异常 scene_%02d: %s", t.scene_id, exc)

            done = sum(1 for t in tasks if t.status in ("completed", "failed"))
            logger.info(
                "  [轮询] %d/%d 完成  (ok=%d fail=%d)",
                done, len(tasks),
                sum(1 for t in tasks if t.status == "completed"),
                sum(1 for t in tasks if t.status == "failed"),
            )

            remaining = [t for t in tasks if t.status not in ("completed", "failed")]
            if remaining:
                time.sleep(self._poll_interval)

        for t in tasks:
            if t.status not in ("completed", "failed"):
                t.status = "timeout"
                t.error = "轮询超时"

    # ── 下载 ─────────────────────────────────────────────────

    def _download_video(self, task: VideoTask) -> None:
        if not task.video_url:
            raise RuntimeError("无 video_url")

        out = VIDEO_DIR / f"scene_{task.scene_id:02d}.mp4"
        resp = requests.get(task.video_url, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"下载失败 {resp.status_code}")

        out = _ensure_unique(out)
        out.write_bytes(resp.content)
        task.output_path = out
        task.status = "completed"


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def generate_video_clips(
    image_paths: list[Path],
    durations: list[float],
    prompts: list[str],
    scene_ids: Optional[list[int]] = None,
) -> VideoBatchResult:
    gen = SeedanceGenerator()
    return gen.generate_clips(image_paths, durations, prompts, scene_ids)


# ═══════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════


def _ensure_unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    counter = 1
    while (parent / f"{stem}_{counter}{suffix}").exists():
        counter += 1
    return parent / f"{stem}_{counter}{suffix}"
