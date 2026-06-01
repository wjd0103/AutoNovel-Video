"""批量生成第1集 镜7~镜22 视频，含角色参考图，记录 Prompt"""
import json
import logging
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from 配置 import config as cfg

API_KEY = cfg.IMAGE_API_KEY
BASE_URL = cfg.IMAGE_API_BASE_URL.rstrip("/")
MODEL = "doubao-seedance-2-0-fast-260128"
VALID_DURS = [4, 5, 6, 8, 10, 12]

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "输出" / "各集" / "第01集" / "视频"
LOG_PATH = BASE_DIR / "输出" / "各集" / "第01集" / "seedance_prompt_log.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SU_WAN_REF = BASE_DIR / "核心" / "输出" / "角色参考图" / "卡通版苏晚.jpeg"
LU_CHENG_AN_REF = BASE_DIR / "核心" / "输出" / "角色参考图" / "陆承安卡通版.jpeg"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("batch_shots_7_22")


def img_to_base64(path):
    ext = path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def round_dur(d):
    return min(VALID_DURS, key=lambda x: abs(x - d))


# ── 镜7~22 分镜数据 ──
shots_data = [
    (7, "固定", "中景", 4, ["苏晚", "陆承安"],
     "岔路口，两人停下。陆承安把伞递给苏晚，动作自然。苏晚接过伞，看着他认真地问。陆承安想了想，认真回答。昏黄路灯，雨幕背景。",
     "陆承安：你拿着吧，明天还在这个位置还我就行。苏晚：你不怕我不还你？陆承安：那就当送你了。"),

    (8, "固定", "近景", 3, ["苏晚", "陆承安"],
     "苏晚攥着伞柄，感受到残留的温度，目送陆承安跑进雨中。他跑出几步回头朝她挥手，笑容温暖。苏晚嘴角微微上扬。雨声渐远。",
     "【雨声渐远】【心跳声】"),

    (9, "拉远", "全景", 4, ["苏晚"],
     "夜晚，苏晚躺在床上，翻来覆去，盯着天花板，嘴角带着一丝笑意。窗外雨声渐小。镜头缓缓拉远，她独自躺在床上的身影越来越小。",
     "【雨声渐弱】【白噪音】苏晚（内心独白）：我甚至不知道他叫什么名字。"),

    (10, "固定", "远景", 3, ["苏晚", "陆承安"],
     "次日黄昏，夕阳西下，操场跑道被拉长的影子。陆承安在跑步，苏晚坐在看台栏杆上，手里拿着那把伞，安静地等他。金色阳光洒满操场。",
     "【风声】【脚步声】"),

    (11, "推近", "中景", 5, ["苏晚", "陆承安"],
     "陆承安跑过苏晚面前，放慢速度，对她微笑，然后继续跑。苏晚看着他的笑容，眼神柔和。画面叠化，他跑了十二圈，她看了十二个笑容。",
     "【风声】【脚步声】苏晚：你怎么跑这么多？"),

    (12, "固定", "近景", 4, ["苏晚", "陆承安"],
     "陆承安停下，气喘吁吁，接过苏晚递来的水，大口喝下，喉结滚动。苏晚问话，他想了想，笑了。夕阳金色光线。",
     "苏晚：为什么心情不好？陆承安（笑）：现在好了。"),

    (13, "固定", "特写", 4, ["苏晚", "陆承安"],
     "图书馆书架间，午后阳光透过窗户，尘埃在光柱中浮动。一只手（陆承安）从苏晚身后伸出，轻松抽出高处的书，然后顺势握住她的手。两只手交握，手心有薄茧。",
     "【翻书声】【安静】"),

    (14, "固定", "中景", 4, ["苏晚", "陆承安"],
     "两人站在书架间，手仍握着，谁也没说话。苏晚低头看着交握的手，眼眶微红。阳光洒在他们身上，画面温暖。尘埃在光柱中缓缓浮动。",
     "【心跳声】【轻柔钢琴BGM起】"),

    (15, "固定", "近景", 4, ["苏晚", "陆承安"],
     "出租屋内，夜晚，灯光温暖。陆承安把一张银行卡放在苏晚手心，眼神认真。苏晚看着他，有些惊讶。桌上摆着草莓。",
     "陆承安：给你保管，以后我赚的每一分钱都给你保管。苏晚：你就不怕我拿了钱跑了？"),

    (16, "推近", "特写", 3, ["苏晚"],
     "苏晚的手打开一个铁盒子，里面放着电影票根、小纸条、贝壳。她小心地将银行卡放入，合上盖子，嘴角带着幸福的笑。镜头缓缓推近铁盒子。",
     "【轻柔钢琴BGM】"),

    (17, "固定", "全景", 3, ["陆承安"],
     "深秋周末，阳光明媚。陆承安站在老小区二楼朝南的阳台上，伸出手感受阳光，笑容温暖。他掏出手机打电话。远处树影摇曳。",
     "【风声】【电话拨号音】陆承安：晚晚，我找到了一个房子。"),

    (18, "固定", "近景", 5, ["苏晚", "陆承安"],
     "苏晚的公寓内，她拿着手绘的房屋改造图，上面密密麻麻标满尺寸和材料。她看着图纸，眼眶湿润，伸手搂住陆承安的脖子，把脸埋在他肩窝。",
     "苏晚：承安，下周一我生日，我们把证领了好不好？陆承安（愣住，紧紧搂住她）：好。"),

    (19, "拉远", "全景", 4, ["苏晚", "陆承安"],
     "夜晚，出租屋小沙发上，两人盖着一条毯子挤在一起聊天。苏晚靠在陆承安肩上，慢慢闭上眼睛，画面温馨。镜头缓缓拉远。",
     "陆承安：以后喊一声陆晚，你俩一起回头。苏晚（笑，打他）：【笑声渐弱】"),

    (20, "固定", "特写", 4, ["苏晚"],
     "苏晚的手机屏幕亮起，来电显示'爸爸'。她接起电话，听着，脸上的笑容逐渐消失，血色褪去，手机从耳边滑落，砸在桌上弹落在地，屏幕碎裂。",
     "【电话里模糊声音】苏父：沈砚下周回国，条件是你和沈砚结婚。【手机落地碎裂声】"),

    (21, "固定", "近景", 3, ["苏晚"],
     "苏晚呆坐在桌前，盯着地上碎裂的手机屏幕，眼神空洞。画面慢慢变暗，只剩她模糊的轮廓。窗外雨声。",
     "【心跳声】【白噪音】"),

    (22, "固定", "远景", 4, [],
     "雨夜，银杏林远景，路灯昏黄，金黄的银杏叶在雨中飘落，地面铺满落叶。画面宁静而忧伤。空镜。",
     "【雨声】【风吹树叶声】【忧伤钢琴BGM】"),
]


def build_content(prompt, char_list, prev_frame_path=None):
    """构建 content 数组：text + 角色参考图 + 上一视频结尾帧"""
    content = [{"type": "text", "text": prompt}]
    refs_used = {}

    # 上一视频的结尾帧作为本视频的起始参考图
    if prev_frame_path and Path(prev_frame_path).is_file():
        content.append({"type": "image_url", "image_url": {"url": img_to_base64(Path(prev_frame_path))}})
        refs_used["_prev_frame"] = str(prev_frame_path)

    # 角色参考图
    if "苏晚" in char_list and SU_WAN_REF.is_file():
        content.append({"type": "image_url", "image_url": {"url": img_to_base64(SU_WAN_REF)}, "role": "reference_image"})
        refs_used["苏晚"] = str(SU_WAN_REF)
    if "陆承安" in char_list and LU_CHENG_AN_REF.is_file():
        content.append({"type": "image_url", "image_url": {"url": img_to_base64(LU_CHENG_AN_REF)}, "role": "reference_image"})
        refs_used["陆承安"] = str(LU_CHENG_AN_REF)
    return content, refs_used


def submit(shot_id, camera, shot_type, duration, char_list, scene_content, audio_content):
    dur = round_dur(duration)
    prompt = f"{shot_type}，{camera}，{scene_content}，温暖电影感画面"
    content, refs = build_content(prompt, char_list)
    payload = {"model": MODEL, "content": content, "duration": dur, "watermark": False}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    r = requests.post(f"{BASE_URL}/contents/generations/tasks", headers=headers, json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"提交失败 [{r.status_code}]: {r.text[:200]}")
    task_id = r.json().get("id", "")
    return {
        "shot_id": shot_id, "task_id": task_id, "duration": dur,
        "prompt": prompt, "refs": refs, "audio": audio_content,
    }


def poll_download(sub):
    sid = sub["shot_id"]
    url = f"{BASE_URL}/contents/generations/tasks/{sub['task_id']}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    deadline = time.time() + 300
    while time.time() < deadline:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            time.sleep(5); continue
        d = r.json(); s = d.get("status", "")
        if s == "succeeded":
            vu = d.get("content", {}).get("video_url", "")
            if vu:
                out_path = OUT_DIR / f"shot_{sid:02d}.mp4"
                v = requests.get(vu, timeout=120)
                out_path.write_bytes(v.content)
                log.info("镜%02d ✅  %ds  %.0f KB", sid, sub["duration"], len(v.content)/1024)
                return sub
        elif s in ("failed", "cancelled", "expired"):
            log.error("镜%02d ❌ %s", sid, d.get("error", {}).get("message", s))
            return None
        time.sleep(6)
    log.error("镜%02d ❌ 超时", sid)
    return None


def main():
    print(f"\n{'═'*60}")
    print("  批量生成第1集 镜7~镜22 视频")
    print(f"{'═'*60}\n")

    # 阶段一：并发提交
    t0 = time.perf_counter()
    submissions = []
    with ThreadPoolExecutor(max_workers=6) as exc:
        futures = {exc.submit(submit, *s): s[0] for s in shots_data}
        for f in as_completed(futures):
            sid = futures[f]
            try:
                sub = f.result()
                submissions.append(sub)
                log.info("镜%02d 提交成功  dur=%ds  task_id=%s", sid, sub["duration"], sub["task_id"][:20])
            except Exception as e:
                log.error("镜%02d 提交失败: %s", sid, e)

    # 阶段二：并发轮询
    print(f"\n  共 {len(submissions)} 个任务已提交，开始轮询...\n")
    results = []
    with ThreadPoolExecutor(max_workers=6) as exc:
        futures = {exc.submit(poll_download, s): s["shot_id"] for s in submissions}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    # 阶段三：记录 Prompt 日志
    prompt_log = []
    if LOG_PATH.is_file():
        prompt_log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    for r in sorted(results, key=lambda x: x["shot_id"]):
        prompt_log.append({
            "shot_id": r["shot_id"],
            "episode": 1,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": r["duration"],
            "prompt": r["prompt"],
            "audio": r["audio"],
            "character_references": r["refs"],
            "model": MODEL,
        })
    LOG_PATH.write_text(json.dumps(prompt_log, ensure_ascii=False, indent=2), encoding="utf-8")

    elapsed = time.perf_counter() - t0
    print(f"\n{'═'*60}")
    print(f"  完成: {len(results)}/{len(shots_data)}  |  耗时: {elapsed:.0f}s")
    print(f"  Prompt 日志: seedance_prompt_log.json ({len(prompt_log)} 条)")
    print(f"  输出目录: {OUT_DIR}")
    print(f"{'═'*60}\n")

    # 已生成列表
    for r in sorted(results, key=lambda x: x["shot_id"]):
        print(f"  ✅ 镜{r['shot_id']:02d}  {r['duration']}s")


if __name__ == "__main__":
    main()
