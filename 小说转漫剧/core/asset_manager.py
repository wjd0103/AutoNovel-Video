"""资产管理器 —— 分镜 JSON → 图片 & 配音的并行生成与下载

读取 StoryboardModel，使用 ThreadPoolExecutor 并发调用生图 API 和 TTS API，
将资产保存到 output/images/ 和 output/audio/。
"""

from __future__ import annotations

import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from openai import OpenAI

from config import config as cfg
from core.storyboard_agent import SceneModel, StoryboardModel

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 输出目录
# ═══════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = PROJECT_ROOT / "output" / "images"
AUDIO_DIR = PROJECT_ROOT / "output" / "audio"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# 结果数据类
# ═══════════════════════════════════════════════════════════════


@dataclass
class AssetTaskResult:
    scene_id: int
    kind: str
    path: Optional[Path] = None
    elapsed: float = 0.0
    success: bool = False
    error: str = ""


@dataclass
class AssetBatchResult:
    image_results: list[AssetTaskResult] = field(default_factory=list)
    audio_results: list[AssetTaskResult] = field(default_factory=list)
    total_elapsed: float = 0.0

    @property
    def image_ok(self) -> int:
        return sum(1 for r in self.image_results if r.success)

    @property
    def audio_ok(self) -> int:
        return sum(1 for r in self.audio_results if r.success)

    @property
    def scene_count(self) -> int:
        return len(self.image_results)


# ═══════════════════════════════════════════════════════════════
# 资产管理器
# ═══════════════════════════════════════════════════════════════


class AssetManager:
    """从 StoryboardModel 批量生成图片和配音。

    用法::

        manager = AssetManager()
        result: AssetBatchResult = manager.generate_all(storyboard)
        print(f"图片 {result.image_ok}/{result.scene_count}  音频 {result.audio_ok}/{result.scene_count}")
    """

    def __init__(
        self,
        image_api_type: Optional[str] = None,
        tts_api_type: Optional[str] = None,
        image_api_key: Optional[str] = None,
        tts_api_key: Optional[str] = None,
        image_api_base_url: Optional[str] = None,
        tts_api_base_url: Optional[str] = None,
        image_model: Optional[str] = None,
        tts_voice: Optional[str] = None,
        tts_speed: float = 1.0,
        max_workers: int = 6,
        characters: Optional[list[dict]] = None,
    ) -> None:
        self._image_type = (image_api_type or cfg.IMAGE_API_TYPE).lower()
        self._tts_type = (tts_api_type or cfg.TTS_API_TYPE).lower()
        self._image_key = image_api_key or cfg.IMAGE_API_KEY
        self._tts_key = tts_api_key or cfg.TTS_API_KEY
        self._image_url = image_api_base_url or cfg.IMAGE_API_BASE_URL
        self._tts_url = tts_api_base_url or cfg.TTS_API_BASE_URL
        self._image_model = image_model or cfg.IMAGE_MODEL
        self._tts_voice = tts_voice or cfg.TTS_VOICE
        self._tts_speed = tts_speed
        self._max_workers = max_workers

        self._char_ref_map: dict[str, str] = {}
        self._char_voice_map: dict[str, str] = {}
        if characters:
            for ch in characters:
                vid = ch.get("voice_id", "")
                ref = ch.get("reference_image", "")
                vname = ch.get("voice_name", "")
                if vid and ref:
                    self._char_ref_map[vid] = ref
                if vid and vname:
                    self._char_voice_map[vid] = vname

        self._openai_client: Optional[OpenAI] = None
        if self._image_type == "openai" and self._image_key:
            self._openai_client = OpenAI(api_key=self._image_key)
        elif self._tts_type == "openai" and self._tts_key and not self._openai_client:
            self._openai_client = OpenAI(api_key=self._tts_key)

        logger.info(
            "AssetManager 初始化  image=%s  tts=%s  workers=%d",
            self._image_type,
            self._tts_type,
            self._max_workers,
        )

    # ── 公开入口 ─────────────────────────────────────────────

    def generate_all(
        self,
        storyboard: StoryboardModel,
    ) -> AssetBatchResult:
        """并行生成全部分镜的图片和音频。

        Args:
            storyboard: StoryboardModel 分镜数据

        Returns:
            AssetBatchResult 包含所有任务的执行结果
        """
        t0 = time.perf_counter()
        scenes = storyboard.scenes

        if not scenes:
            logger.warning("分镜列表为空，跳过生成")
            return AssetBatchResult(total_elapsed=0)

        batch_id = _short_id()
        logger.info("=" * 60)
        logger.info("开始批量生成资产  分镜数=%d  batch=%s", len(scenes), batch_id)
        logger.info("  生图后端: %s  TTS 后端: %s", self._image_type, self._tts_type)

        image_results: list[AssetTaskResult] = []
        audio_results: list[AssetTaskResult] = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_map: dict = {}

            for scene in scenes:
                f_img = executor.submit(self._generate_one_image, scene, batch_id)
                future_map[f_img] = AssetTaskResult(scene_id=scene.id, kind="image")

            for scene in scenes:
                f_aud = executor.submit(self._generate_one_audio, scene, batch_id)
                future_map[f_aud] = AssetTaskResult(scene_id=scene.id, kind="audio")

            completed = 0
            total = len(future_map)
            for future in as_completed(future_map):
                completed += 1
                template = future_map[future]
                try:
                    result = future.result()
                    if template.kind == "image":
                        image_results.append(result)
                    else:
                        audio_results.append(result)
                    status = "OK" if result.success else "FAIL"
                    marker = "✅" if result.success else "❌"
                    logger.info(
                        "  [%2d/%2d] %s scene_%02d  %s  %.1fs  %s",
                        completed,
                        total,
                        marker,
                        result.scene_id,
                        result.kind,
                        result.elapsed,
                        status,
                    )
                except Exception as exc:
                    failed = AssetTaskResult(
                        scene_id=template.scene_id,
                        kind=template.kind,
                        elapsed=0,
                        success=False,
                        error=str(exc),
                    )
                    if template.kind == "image":
                        image_results.append(failed)
                    else:
                        audio_results.append(failed)
                    logger.error(
                        "  [%2d/%2d] ❌ scene_%02d  %s  异常: %s",
                        completed,
                        total,
                        template.scene_id,
                        template.kind,
                        exc,
                    )

        total_elapsed = time.perf_counter() - t0
        result = AssetBatchResult(
            image_results=sorted(image_results, key=lambda r: r.scene_id),
            audio_results=sorted(audio_results, key=lambda r: r.scene_id),
            total_elapsed=total_elapsed,
        )

        logger.info("=" * 60)
        logger.info(
            "批量生成完成  图片 %d/%d  音频 %d/%d  总耗时 %.1fs",
            result.image_ok,
            result.scene_count,
            result.audio_ok,
            result.scene_count,
            total_elapsed,
        )
        return result

    # ── 单任务包装器 ─────────────────────────────────────────

    def _generate_one_image(self, scene: SceneModel, batch_id: str) -> AssetTaskResult:
        t0 = time.perf_counter()
        try:
            output_path = IMAGE_DIR / f"scene_{scene.id:02d}.png"
            output_path = _ensure_unique(output_path)

            handler = getattr(self, f"_image_{self._image_type.replace('-', '_')}", None)
            if handler is None:
                raise NotImplementedError(f"不支持的生图后端: {self._image_type}")

            ref_images: list[str] = []
            for ch_id in scene.character_list:
                for vid in self._char_ref_map:
                    if vid.replace("_", "") in ch_id.replace("_", "").replace(" ", "").lower():
                        ref_url = self._char_ref_map[vid]
                        if ref_url:
                            ref_images.append(ref_url)

            image_bytes = handler(scene.image_prompt, ref_images=ref_images if ref_images else None)
            output_path.write_bytes(image_bytes)

            elapsed = time.perf_counter() - t0
            logger.debug("  图片生成成功 scene_%02d  size=%s  %.1fs", scene.id, _fmt_size(output_path), elapsed)
            return AssetTaskResult(scene_id=scene.id, kind="image", path=output_path, elapsed=elapsed, success=True)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.debug("  图片生成失败 scene_%02d  %.1fs  %s", scene.id, elapsed, exc)
            return AssetTaskResult(
                scene_id=scene.id,
                kind="image",
                elapsed=elapsed,
                success=False,
                error=str(exc),
            )

    def _generate_one_audio(self, scene: SceneModel, batch_id: str) -> AssetTaskResult:
        t0 = time.perf_counter()
        try:
            output_path = AUDIO_DIR / f"scene_{scene.id:02d}.mp3"
            output_path = _ensure_unique(output_path)

            handler = getattr(self, f"_tts_{self._tts_type.replace('-', '_')}", None)
            if handler is None:
                raise NotImplementedError(f"不支持的 TTS 后端: {self._tts_type}")

            audio_bytes = handler(scene.dialogue, scene.voice_id)
            output_path.write_bytes(audio_bytes)

            elapsed = time.perf_counter() - t0
            logger.debug("  配音生成成功 scene_%02d  voice=%s  %.1fs", scene.id, scene.voice_id, elapsed)
            return AssetTaskResult(scene_id=scene.id, kind="audio", path=output_path, elapsed=elapsed, success=True)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.debug("  配音生成失败 scene_%02d  %.1fs  %s", scene.id, elapsed, exc)
            return AssetTaskResult(
                scene_id=scene.id,
                kind="audio",
                elapsed=elapsed,
                success=False,
                error=str(exc),
            )

    # ── 生图后端 ─────────────────────────────────────────────

    def _image_openai(self, prompt: str) -> bytes:
        """OpenAI DALL·E 3 生图。"""
        if not self._openai_client:
            raise RuntimeError("OpenAI client 未初始化")
        if not self._image_key:
            raise RuntimeError("IMAGE_API_KEY 未设置")

        # 用 DALL·E 2 以获取 URL（DALL·E 3 在某些 key 下返回 base64）
        response = self._openai_client.images.generate(
            model="dall-e-2",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        url = response.data[0].url
        if not url:
            raise RuntimeError("DALL·E 未返回图片 URL")
        return requests.get(url, timeout=60).content

    def _image_doubao(self, prompt: str, ref_images: Optional[list[str]] = None) -> bytes:
        """豆包 Seedream 生图（火山引擎 Ark API）。

        接口: POST /images/generations
        Seedream 5.0 要求 size 为 2k/3k/4k 或 WIDTHxHEIGHT（最低 3686400 像素）。
        支持传入参考图 URL 以实现角色一致性。

        参考: https://www.volcengine.com/docs/82379/1541523
        """
        if not self._image_key:
            raise RuntimeError("IMAGE_API_KEY 未设置")

        base = self._image_url.rstrip("/")

        img_w = cfg.OUTPUT.width
        img_h = cfg.OUTPUT.height
        total_px = img_w * img_h

        if total_px < 3_686_400:
            size_str = "2k"
        elif total_px <= 4_096 * 4_096:
            size_str = f"{img_w}x{img_h}"
        else:
            size_str = "4k"

        payload: dict = {
            "model": self._image_model,
            "prompt": prompt,
            "size": size_str,
            "response_format": "url",
            "watermark": False,
            "sequential_image_generation": "disabled",
            "stream": False,
        }

        if ref_images:
            payload["image"] = ref_images if len(ref_images) > 1 else ref_images[0]
            logger.debug("  豆包生图 含 %d 张参考图", len(ref_images))

        resp = requests.post(
            f"{base}/images/generations",
            headers={
                "Authorization": f"Bearer {self._image_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"豆包生图 API 返回 {resp.status_code}: {resp.text[:300]}"
            )

        body = resp.json()
        data_list = body.get("data", [])
        if not data_list:
            raise RuntimeError("豆包生图 API 未返回图片数据")

        url = data_list[0].get("url", "")
        if not url:
            raise RuntimeError("豆包生图 API 返回的 data 中缺少 url")

        logger.debug("  豆包生图 url 获取成功，正在下载…")
        img_bytes = requests.get(url, timeout=60).content
        return img_bytes

    def _image_stable_diffusion(self, prompt: str) -> bytes:
        """Stability AI REST API 生图。

        平台: https://platform.stability.ai
        """
        if not self._image_key:
            raise RuntimeError("IMAGE_API_KEY 未设置")

        base = self._image_url or "https://api.stability.ai"
        resp = requests.post(
            f"{base}/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
            headers={
                "Authorization": f"Bearer {self._image_key}",
                "Accept": "image/png",
            },
            json={
                "text_prompts": [{"text": prompt, "weight": 1.0}],
                "cfg_scale": 7,
                "steps": 30,
                "width": 1024,
                "height": 1024,
            },
            timeout=90,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Stability AI 返回 {resp.status_code}: {resp.text[:300]}")
        return resp.content

    def _image_comfyui(self, prompt: str) -> bytes:
        """ComfyUI 本地/远程 API 生图。

        需要先在 ComfyUI 中加载一个 text-to-image workflow。

        Args:
            prompt: 英文绘图提示词
            base_url: ComfyUI 服务地址（如 http://127.0.0.1:8188）
        """
        if not self._image_url:
            raise RuntimeError("ComfyUI 地址未设置（IMAGE_API_BASE_URL）")

        base = self._image_url.rstrip("/")

        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {"seed": int(time.time()), "steps": 20, "cfg": 7, "sampler_name": "euler", "scheduler": "normal", "denoise": 1},
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "comfyui", "images": ["8", 0]},
            },
            "10": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "anime style, consistent character design, cinematic lighting", "clip": ["4", 1]},
            },
        }
        for node_id in ["3", "4", "5", "6", "7", "8", "9", "10"]:
            workflow[node_id]["_meta"] = {"title": f"node_{node_id}"}

        prompt_data = {
            "prompt": workflow,
            "client_id": f"asset_manager_{os.getpid()}",
        }

        resp = requests.post(f"{base}/prompt", json=prompt_data, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"ComfyUI prompt 提交失败 {resp.status_code}: {resp.text[:300]}")
        prompt_id = resp.json().get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI 未返回 prompt_id")

        for attempt in range(120):
            time.sleep(2)
            history_resp = requests.get(f"{base}/history/{prompt_id}", timeout=10)
            if history_resp.status_code != 200:
                continue
            history = history_resp.json()
            outputs = history.get(prompt_id, {}).get("outputs")
            if not outputs:
                continue
            for node_id, node_output in outputs.items():
                images = node_output.get("images", [])
                if images:
                    img_filename = images[0]["filename"]
                    img_type = images[0].get("type", "output")
                    img_resp = requests.get(f"{base}/view?filename={img_filename}&type={img_type}", timeout=30)
                    if img_resp.status_code == 200:
                        return img_resp.content
            time.sleep(2)

        raise RuntimeError(f"ComfyUI 生成超时 (prompt_id={prompt_id})")

    # ── TTS 后端 ─────────────────────────────────────────────

    def _tts_openai(self, text: str, voice_id: str) -> bytes:
        """OpenAI TTS API 语音合成。"""
        if not self._openai_client:
            raise RuntimeError("OpenAI client 未初始化")
        if not self._tts_key:
            raise RuntimeError("TTS_API_KEY 未设置")

        voice = self._tts_voice
        if voice_id in ("female_lead", "female_lead_01"):
            voice = "nova"
        elif voice_id == "male_lead":
            voice = "onyx"
        elif voice_id == "narrator":
            voice = "echo"

        response = self._openai_client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            speed=self._tts_speed,
            response_format="mp3",
        )
        buffer = io.BytesIO()
        for chunk in response.iter_bytes(chunk_size=4096):
            buffer.write(chunk)
        return buffer.getvalue()

    def _tts_edge_tts(self, text: str, voice_id: str) -> bytes:
        r"""Microsoft Edge TTS（免费、无需 API Key）。"""
        import subprocess
        import tempfile

        default_map = {
            "narrator": "zh-CN-YunxiNeural",
            "male_lead": "zh-CN-YunxiNeural",
            "female_lead": "zh-CN-XiaoxiaoNeural",
            "female_lead_01": "zh-CN-XiaoxiaoNeural",
            "supporting_male": "zh-CN-YunyangNeural",
            "supporting_female": "zh-CN-XiaoyiNeural",
        }

        edge_voice = self._char_voice_map.get(voice_id) or default_map.get(voice_id, self._tts_voice)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            subprocess.run(
                [
                    "python3", "-m", "edge_tts",
                    "--voice", edge_voice,
                    "--text", text,
                    "--write-media", tmp_path,
                ],
                capture_output=True,
                timeout=60,
                check=True,
            )
            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _tts_volcengine(self, text: str, voice_id: str) -> bytes:
        """火山引擎 TTS（字节跳动）。"""
        if not self._tts_key or not self._tts_url:
            raise RuntimeError("TTS_API_KEY 或 TTS_API_BASE_URL 未设置")

        voice_map = {
            "narrator": "BV700_streaming",
            "male_lead": "BV406_streaming",
            "female_lead": "BV700_streaming",
            "female_lead_01": "BV700_streaming",
            "supporting_male": "BV406_streaming",
            "supporting_female": "BV700_streaming",
        }
        volc_voice = voice_map.get(voice_id, "BV700_streaming")

        payload = {
            "app": {"appid": self._tts_key.split(",")[0] if "," in self._tts_key else ""},
            "user": {"uid": "asset_manager"},
            "audio": {
                "voice_type": volc_voice,
                "encoding": "mp3",
                "speed_ratio": self._tts_speed,
            },
            "request": {
                "reqid": f"scene_{int(time.time())}",
                "text": text,
                "text_type": "plain",
                "operation": "query",
            },
        }
        resp = requests.post(
            self._tts_url.rstrip("/") + "/api/v1/tts",
            headers={"Authorization": f"Bearer {self._tts_key}"},
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"火山引擎 TTS 返回 {resp.status_code}: {resp.text[:300]}")
        return resp.content

    # ── voice_id → TTS 角色映射（供下游参考） ────────────────

    @staticmethod
    def voice_to_tts_config(voice_id: str) -> dict:
        """根据 voice_id 返回推荐的 TTS 音色配置。"""
        mapping = {
            "narrator": {"openai": "echo", "edge": "zh-CN-YunxiNeural", "volc": "BV700_streaming"},
            "male_lead": {"openai": "onyx", "edge": "zh-CN-YunxiNeural", "volc": "BV406_streaming"},
            "female_lead": {"openai": "nova", "edge": "zh-CN-XiaoxiaoNeural", "volc": "BV700_streaming"},
            "female_lead_01": {"openai": "nova", "edge": "zh-CN-XiaoxiaoNeural", "volc": "BV700_streaming"},
            "supporting_male": {"openai": "alloy", "edge": "zh-CN-YunyangNeural", "volc": "BV406_streaming"},
            "supporting_female": {"openai": "shimmer", "edge": "zh-CN-XiaoyiNeural", "volc": "BV700_streaming"},
        }
        return mapping.get(voice_id, {"openai": "alloy", "edge": "zh-CN-YunxiNeural", "volc": "BV700_streaming"})


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════


def generate_assets(
    storyboard: StoryboardModel,
    max_workers: int = 6,
    characters: Optional[list[dict]] = None,
) -> AssetBatchResult:
    """一行调用，批量生成图片和配音。

    Args:
        storyboard: StoryboardModel 分镜数据
        max_workers: 并发线程数
        characters: 角色配置列表（用于参考图一致性 + TTS 音色映射）
    """
    manager = AssetManager(max_workers=max_workers, characters=characters)
    return manager.generate_all(storyboard)


def generate_character_and_scene_image(prompt: str, scene_id: int) -> Optional[Path]:
    """生成单张分镜图片。

    返回保存路径，失败返回 None。
    建议通过 :class:`AssetManager` 批量调用以获得并发加速。
    """
    manager = AssetManager()
    result = manager._generate_one_image(
        SceneModel(
            id=scene_id,
            character_list=[],
            image_prompt=prompt,
            dialogue="",
            voice_id="narrator",
            camera_movement="static",
        ),
        batch_id="",
    )
    return result.path if result.success else None


def generate_voice_tts(dialogue: str, voice_id: str, scene_id: int) -> Optional[Path]:
    """生成单段配音。

    返回保存路径，失败返回 None。
    建议通过 :class:`AssetManager` 批量调用以获得并发加速。
    """
    manager = AssetManager()
    result = manager._generate_one_audio(
        SceneModel(
            id=scene_id,
            character_list=[],
            image_prompt="",
            dialogue=dialogue,
            voice_id=voice_id,
            camera_movement="static",
        ),
        batch_id="",
    )
    return result.path if result.success else None


# ═══════════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════════


def _ensure_unique(path: Path) -> Path:
    """如果文件已存在，添加数字后缀避免覆盖。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    counter = 1
    while (parent / f"{stem}_{counter}{suffix}").exists():
        counter += 1
    return parent / f"{stem}_{counter}{suffix}"


def _fmt_size(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


def _short_id() -> str:
    return os.urandom(3).hex()
