"""生成第1集 镜6 — 含苏晚+陆承安角色参考图，记录 Seedance Prompt"""
import logging, time, requests, base64, json
from pathlib import Path

from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"
VALID_DURS = [4, 5, 6, 8, 10, 12]

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "输出" / "各集" / "第01集" / "视频"
PROMPT_LOG_DIR = BASE_DIR / "输出" / "各集" / "第01集"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("shot6")

SU_WAN_REF = BASE_DIR / "核心" / "输出" / "角色参考图" / "卡通版苏晚.jpeg"
LU_CHENG_AN_REF = BASE_DIR / "核心" / "输出" / "角色参考图" / "陆承安卡通版.jpeg"


def img_to_base64(path: Path) -> str:
    ext = path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def round_dur(d):
    return min(VALID_DURS, key=lambda x: abs(x - d))


# ── 镜6 Prompt（分镜原始描述+角色外貌+镜头运动） ──
prompt = (
    "跟拍镜头，全景，大学雨夜，一对年轻男女共撑一把小伞走在雨中。"
    "黑长直发的女生和旁边的高大男生挤在一把伞下，伞面明显偏向女生一侧，"
    "男生的右肩完全暴露在雨中，雨水顺着他的下颌流淌。女生侧头看他，发现他的动作，眼神微动。"
    "昏黄路灯，地面湿漉漉反射光影，温暖电影感画面。"
)

duration = round_dur(4)

# ── 构建传给 Seedance 的 payload ──
content = [{"type": "text", "text": prompt}]

refs_info = {}
if SU_WAN_REF.is_file():
    content.append({"type": "image_url", "image_url": {"url": img_to_base64(SU_WAN_REF)}, "role": "reference_image"})
    refs_info["苏晚"] = str(SU_WAN_REF)
if LU_CHENG_AN_REF.is_file():
    content.append({"type": "image_url", "image_url": {"url": img_to_base64(LU_CHENG_AN_REF)}, "role": "reference_image"})
    refs_info["陆承安"] = str(LU_CHENG_AN_REF)

payload = {"model": MODEL, "content": content, "duration": duration, "watermark": False}
headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# ── 输出 Prompt 记录 ──
print(f"\n{'═'*60}")
print("  【镜6】两人共伞雨中同行 — 跟拍全景")
print(f"{'═'*60}\n")

print("── 发送给 Seedance 的完整 Prompt ──")
print()
print(prompt)
print()
print(f"  时长: {duration}s")
print(f"  角色参考图: {len(refs_info)} 张")
for name, path in refs_info.items():
    p = Path(path)
    print(f"    {name}: {p.name}  ({p.stat().st_size // 1024} KB)")
print()

# ── 保存 prompt 到日志文件 ──
prompt_log = {
    "shot_id": 6,
    "episode": 1,
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "duration": duration,
    "prompt": prompt,
    "character_references": {name: str(p) for name, p in refs_info.items()},
    "model": MODEL,
}
log_path = PROMPT_LOG_DIR / "seedance_prompt_log.json"
existing = []
if log_path.is_file():
    existing = json.loads(log_path.read_text(encoding="utf-8"))
existing.append(prompt_log)
log_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
log.info("Prompt 已记录: seedance_prompt_log.json")

# ── 提交 Seedance ──
log.info("提交 Seedance 任务...")
r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
if r.status_code != 200:
    log.error("提交失败 [%d]: %s", r.status_code, r.text[:300])
    print(f"\n  ❌ 提交失败: {r.text[:200]}\n")
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
            out_path = OUT_DIR / "shot_06.mp4"
            v = requests.get(vu, timeout=120)
            out_path.write_bytes(v.content)
            log.info("✅ 镜6 下载完成  %.0f KB", len(v.content)/1024)
            print(f"\n  ✅ 视频已保存: {out_path}\n")
            break
    elif s in ("failed", "cancelled", "expired"):
        log.error("❌ 失败: %s", d.get("error", {}).get("message", s))
        break
    time.sleep(6)
