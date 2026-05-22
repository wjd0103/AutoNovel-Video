#!/usr/bin/env python3
"""
番茄小说章节自动发布器
========================
通过 Selenium + Chrome 浏览器自动化，将本地章节发布到番茄小说作家后台。

前置条件：已通过 Chrome 浏览器手动登录番茄小说作家后台（cookie 生效中）。

用法：
    # 增量发布（发布所有未发布章节）
    python 自动化/发布器/发布器.py

    # 发布指定章节
    python 自动化/发布器/发布器.py --chapter 1

    # 批量发布
    python 自动化/发布器/发布器.py --start 1 --end 10

    # 预览模式（不实际发布）
    python 自动化/发布器/发布器.py --dry-run
"""

import re
import sys
import time
import yaml
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

# ---------- 项目路径 ----------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AUTOMATION_DIR = PROJECT_ROOT / "自动化"
CONFIG_DIR = AUTOMATION_DIR / "配置"
LOG_DIR = AUTOMATION_DIR / "日志"
CONFIG_FILE = CONFIG_DIR / "发布配置.yaml"
PUBLISHED_LOG_DIR = LOG_DIR
# CHAPTERS_DIR 延迟初始化——从配置中读取小说目录后动态设置
CHAPTERS_DIR = None

# 当前项目名（由 load_config / main 设置），用于隔离各项目的数据
CURRENT_PROJECT_NAME = ""

# ---------- 日志 ----------
LOG_FILE = LOG_DIR / f"发布日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ============================================================
# 章节文件解析
# ============================================================

def parse_chapter_filename(filename: str) -> Optional[Tuple[int, str]]:
    pattern = r"^第(\d+)章[·\.,，、\s]*(.+)\.md$"
    match = re.match(pattern, filename)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def discover_chapters() -> List[Tuple[int, str, Path]]:
    global CHAPTERS_DIR
    if not CHAPTERS_DIR:
        log.error("CHAPTERS_DIR 未初始化，请检查配置中的「小说目录」字段")
        return []
    chapters = []
    if not CHAPTERS_DIR.exists():
        log.warning(f"章节目录不存在: {CHAPTERS_DIR}")
        return chapters
    for f in CHAPTERS_DIR.glob("第*.md"):
        parsed = parse_chapter_filename(f.name)
        if parsed:
            chapters.append((parsed[0], parsed[1], f))
    chapters.sort(key=lambda x: x[0])
    return chapters


def read_chapter_content(filepath: Path) -> str:
    return filepath.read_text(encoding="utf-8").strip()


# ============================================================
# 已发布记录管理
# ============================================================

def get_published_log_path() -> Path:
    project_name = CURRENT_PROJECT_NAME or "default"
    return PUBLISHED_LOG_DIR / f"已发布章节_{project_name}.txt"


def load_published_history() -> set:
    published_log = get_published_log_path()
    if not published_log.exists():
        return set()
    published = set()
    for line in published_log.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line and line.isdigit():
            published.add(int(line))
    return published


def save_published_history(chapter_num: int, title: str):
    published_log = get_published_log_path()
    published_log.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(published_log, "a", encoding="utf-8") as f:
        f.write(f"{chapter_num}\t{title}\t{timestamp}\n")


# ============================================================
# 浏览器自动化核心
# ============================================================

class FanqiePublisher:
    """番茄小说作家后台自动发布器（已登录模式）"""

    # ---- 平台页面 URL 模板 ----
    # 真实番茄小说作家后台地址
    WRITER_HOME = "https://fanqienovel.com/main/writer/"
    # 新建章节 URL 模式:
    #   {work_id}     — 作品 ID（如 7639950067528387646）
    #   {target_id}   — 发布目标 ID（如 7639969329018044990，从章节管理页 URL 提取）
    NEW_CHAPTER = "https://fanqienovel.com/main/writer/{work_id}/publish/{target_id}"
    # 作品章节列表页（可选，用于确认作品状态）
    WORK_DETAIL = "https://fanqienovel.com/main/writer/{work_id}"

    # ---- 错别字提醒弹窗的可能选择器 ----
    # 番茄在点击"发布"后可能弹出错别字检查提醒，需要关闭它才能继续
    TYPO_CHECK_SELECTORS = [
        # 弹窗关闭按钮
        "//button[contains(text(),'忽略')]",
        "//button[contains(text(),'继续发布')]",
        "//button[contains(text(),'仍然发布')]",
        "//button[contains(text(),'关闭')]",
        "//span[contains(text(),'忽略')]",
        "//span[contains(text(),'继续')]",
        # 弹窗右上角 X
        "//*[contains(@class,'close')]",
        "//*[contains(@class,'dialog')]//button",
        # 遮罩层点击关闭
        "//*[contains(@class,'overlay') or contains(@class,'mask')]",
        # 确认弹窗的确定按钮
        "//button[contains(text(),'确定')]",
        "//button[contains(text(),'知道了')]",
        # 直接点发布（重试）
        "//button[contains(text(),'发布')]",
    ]

    def __init__(self, config: dict):
        self.config = config
        self.driver = None
        self.wait = None
        self.work_id = config.get("作品", {}).get("作品ID", "")
        self.target_id = config.get("作品", {}).get("发布目标ID", "")
        self.typo_auto_ignore = config.get("发布行为", {}).get("自动忽略错别字提醒", True)

    # ---- 浏览器生命周期 ----

    def _init_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        # 使用项目专用 Chrome profile，避免与用户日常 Chrome 冲突
        # 首次运行需在此窗口手动登录番茄小说，之后 cookie 持久生效
        browser_config = self.config.get("浏览器", {})
        profile_dir_config = browser_config.get("用户数据目录", "自动化/chrome_profiles/default")
        profile_path = Path(profile_dir_config)
        if not profile_path.is_absolute():
            profile_path = PROJECT_ROOT / profile_path
        profile_dir = str(profile_path)
        profile_path.mkdir(parents=True, exist_ok=True)
        book_name = self.config.get("作品", {}).get("书名", "未知作品")
        log.info(f"Chrome 用户数据目录: {profile_dir}（作品: {book_name}）")

        # 清理上次异常退出残留的单例锁文件（不清理 Chrome 无法启动）
        for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lock_path = profile_path / lock_name
            if lock_path.exists() or lock_path.is_symlink():
                lock_path.unlink(missing_ok=True)
        log.info("Chrome profile 锁文件已清理")

        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-background-mode")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        timeout = self.config.get("浏览器", {}).get("加载超时", 30)
        # 使用 /tmp/chromedriver（Chrome 147 匹配版本）
        service = Service(executable_path="/tmp/chromedriver")
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.set_page_load_timeout(timeout)
        self.wait = WebDriverWait(self.driver, timeout)
        log.info("Chrome 浏览器已启动（已登录模式）")

    def start(self):
        self._init_driver()

    def quit(self):
        if self.driver:
            self.driver.quit()
            log.info("浏览器已关闭")

    def _sleep(self, multiplier: float = 1.0):
        base = self.config.get("浏览器", {}).get("操作间隔", 2)
        time.sleep(base * multiplier)

    # ---- 作品导航 ----

    def navigate_to_work(self) -> bool:
        """
        导航到番茄小说作家工作台。
        如果未登录，等待用户在 Chrome 窗口中手动登录后确认继续。
        """
        log.info("正在打开作家工作台...")
        self.driver.get(self.WRITER_HOME)
        self._sleep(3)

        # 检测是否被重定向到登录页
        if "login" in self.driver.current_url.lower():
            print("\n" + "=" * 60)
            print("  ⚠️  尚未登录番茄小说")
            print("  请在自动打开的 Chrome 窗口中完成登录")
            print("  登录后可按 Enter 继续，或等待自动检测（最长 120 秒）")
            print("=" * 60)

            # 后台线程等待用户按 Enter（兼容沙箱环境，EOF 时静默退出）
            import threading
            enter_pressed = False

            def wait_enter():
                nonlocal enter_pressed
                try:
                    input()
                    enter_pressed = True
                except Exception:
                    pass

            t = threading.Thread(target=wait_enter, daemon=True)
            t.start()

            # 主线程轮询 URL（不刷新页面，避免打断用户登录）
            for attempt in range(40):
                self._sleep(3)
                try:
                    current = self.driver.current_url.lower()
                    if "login" not in current:
                        log.info("检测到登录成功")
                        return True
                except Exception:
                    pass
                if enter_pressed:
                    log.info("用户按 Enter 确认")
                    break
                if attempt % 5 == 4:
                    print(f"  ⏳ 等待登录中...（已等待 {(attempt + 1) * 3} 秒）")

            # 用户按 Enter 后，重新导航到工作台确认登录状态
            if enter_pressed:
                self.driver.get(self.WRITER_HOME)
                self._sleep(3)
                if "login" not in self.driver.current_url.lower():
                    log.info("已进入作家工作台")
                    return True
                log.error("登录未生效，请重新运行脚本")
                return False

            log.error("登录超时（120秒），请重新运行脚本并在 Chrome 窗口中完成登录")
            return False

        if "writer" in self.driver.current_url:
            log.info("已进入作家工作台")
            return True
        log.error("未能进入作家工作台")
        return False

    def _ensure_on_work_page(self) -> bool:
        """确保当前页面是作品详情/章节管理页"""
        if self.work_id and self.work_id in self.driver.current_url:
            return True
        if self.work_id:
            url = self.WORK_DETAIL.format(work_id=self.work_id)
            self.driver.get(url)
            self._sleep(2)
            return True
        return False

    # ---- 错别字提醒处理 ----

    def _dismiss_typo_check(self) -> bool:
        """
        检测并关闭番茄小说的错别字提醒弹窗。
        番茄在点击发布后会扫描正文，如果有疑似错别字会弹窗提醒。
        此方法遍历可能的弹窗元素，尝试关闭/忽略。
        """
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException, ElementNotInteractableException

        dismissed = False
        for selector in self.TYPO_CHECK_SELECTORS:
            try:
                elements = self.driver.find_elements(By.XPATH, selector)
                for el in elements:
                    try:
                        if el.is_displayed() and el.is_enabled():
                            el.click()
                            dismissed = True
                            log.info(f"已关闭错别字提醒弹窗 (selector: {selector})")
                            self._sleep(0.5)
                            break
                    except ElementNotInteractableException:
                        continue
            except Exception:
                continue

        # 备用方案：按 Escape 键关闭弹窗
        if not dismissed:
            try:
                from selenium.webdriver.common.keys import Keys
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                log.info("已按 ESC 关闭弹窗")
                dismissed = True
                self._sleep(0.5)
            except Exception:
                pass

        return dismissed

    def _click_button(self, text_list, force=False):
        """查找并点击包含指定文字的按钮，JS 点击兜底（忽略 disabled 状态）"""
        from selenium.webdriver.common.by import By
        for text in text_list:
            btns = self.driver.find_elements(By.XPATH,
                f"//button[contains(text(),'{text}')] | //span[contains(text(),'{text}')]")
            for btn in btns:
                try:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        log.info(f"  已点击: {text}")
                        return True
                except Exception:
                    pass
        return False

    def _click_button_and_wait(self, text_list, wait_sec=3):
        """点击按钮并等待页面跳转/弹窗"""
        if self._click_button(text_list):
            self._sleep(wait_sec)
            # 检测页面是否发生了变化（URL 变化或新按钮出现）
            return True
        return False

    def _wait_for_button(self, target_texts, timeout_sec=30):
        """轮询等待指定按钮出现，返回所有可见按钮文本列表"""
        from selenium.webdriver.common.by import By
        for attempt in range(timeout_sec // 5):
            btns = self.driver.find_elements(By.TAG_NAME, "button")
            visible_texts = []
            for b in btns:
                try:
                    if b.is_displayed():
                        t = b.text.strip()
                        if t:
                            visible_texts.append(t)
                except Exception:
                    pass
            log.info(f"  第{attempt+1}次检查，可见按钮: {visible_texts}")
            if any(any(target in t for target in target_texts) for t in visible_texts):
                return visible_texts
            self._sleep(5)
        return []

    # ---- 发布章节 ----

    def publish_chapter(self, chapter_num: int, title: str, content: str) -> bool:
        """
        番茄小说发布流程是两步表单：
          第一步：填写章节号 + 标题 + 正文 → 点击「下一步」
          第二步：预览/确认 → 点击「发布」

        必须用 click + send_keys 模拟真人输入，不能直接用 execute_script 设值——
        页面是 React/Vue 框架，JS 直接改 DOM 不会更新组件内部状态。
        """
        log.info(f"正在发布: 第{chapter_num}章 {title}")

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys

            # ===== 第一步：进入发布页 =====
            # 直接打开 publish 路径（不带 target_id），让服务器自动分配
            pub_url = f"https://fanqienovel.com/main/writer/{self.work_id}/publish/"
            self.driver.get(pub_url)
            self._sleep(4)

            # 检查是否正常加载了发布表单
            log.info(f"  当前URL: {self.driver.current_url}")
            visible = self._wait_for_button(["下一步"])
            if not visible:
                # 如果重定向到了管理页，尝试点击「创建章节」
                log.warning("「下一步」未出现，重定向到管理页，点击「创建章节」...")
                self._click_button(["创建章节"])
                self._sleep(4)
                # 检查是否新标签页
                if len(self.driver.window_handles) > 1:
                    self.driver.switch_to.window(self.driver.window_handles[-1])
                    log.info(f"  切换到新标签页: {self.driver.current_url}")
                visible = self._wait_for_button(["下一步"])
                if not visible:
                    log.error(f"  最终URL: {self.driver.current_url}")
                    self.driver.save_screenshot(str(LOG_DIR / "debug" / f"step1_timeout_{chapter_num}.png"))
                    return False
            self.driver.save_screenshot(str(LOG_DIR / "debug" / f"step1_{chapter_num}.png"))
            html_path = LOG_DIR / "debug" / f"page_html_{chapter_num}.html"
            html_path.write_text(self.driver.page_source, encoding="utf-8")
            log.info(f"  页面 HTML 已保存: {html_path}")

            # 进入字段填写逻辑
            return self._fill_publish_form(chapter_num, title, content)

        except Exception as e:
            log.error(f"发布第{chapter_num}章时出错: {e}")
            return False

    def _fill_publish_form(self, chapter_num: int, title: str, content: str) -> bool:
        """填充发布表单的三个字段并完成发布"""
        log.info("填充发布表单...")
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys

            # ---- 找到三个表单字段 ----
            # 章节号 input：页面第一个可见 input，在标题 input 前面，无 placeholder
            title_input = None
            chapter_input = None
            all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
            for i, inp in enumerate(all_inputs):
                try:
                    if not inp.is_displayed():
                        continue
                    ph = inp.get_attribute("placeholder") or ""
                    if "标题" in ph:
                        title_input = inp
                        # 向前找第一个可见 input = 章节号
                        for j in range(i - 1, -1, -1):
                            try:
                                if all_inputs[j].is_displayed():
                                    chapter_input = all_inputs[j]
                                    break
                            except Exception:
                                continue
                        break
                except Exception:
                    pass

            # 正文编辑器
            body_editor = None
            for sel in [".ProseMirror[contenteditable='true']", "[contenteditable='true']"]:
                eds = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for ed in eds:
                    try:
                        if ed.is_displayed() and ed.size.get("height", 0) > 60:
                            body_editor = ed
                            break
                    except Exception:
                        pass
                if body_editor:
                    break

            # ---- 1. 填章节号 ----
            if chapter_input:
                self.driver.execute_script("arguments[0].click();", chapter_input)
                self._sleep(0.3)
                chapter_input.send_keys(Keys.COMMAND, "a")
                chapter_input.send_keys(str(chapter_num))
                log.info(f"  章节号已填入: {chapter_num}")
            else:
                log.error("未找到章节号输入框，尝试 JS fallback...")
                self.driver.execute_script(
                    "var inp=document.querySelector('input.serial-input');"
                    "if(inp){inp.value='" + str(chapter_num) + "';"
                    "inp.dispatchEvent(new Event('input',{bubbles:true}));"
                    "inp.dispatchEvent(new Event('change',{bubbles:true}));}")

            # ---- 2. 填标题 ----
            if title_input:
                self.driver.execute_script("arguments[0].click();", title_input)
                self._sleep(0.3)
                title_input.send_keys(Keys.COMMAND, "a")
                title_input.send_keys(title)
                log.info(f"  标题已填入: {title}")
            else:
                log.warning("未找到标题输入框")

            # ---- 3. 填正文（ProseMirror 专用方案） ----
            # ProseMirror 是 React 富文本编辑器，不响应普通的 send_keys/粘贴
            # 必须用 innerHTML 注入 + 触发完整的 input/change 事件链
            if body_editor:
                # 构建 HTML（每段一个 <p>）
                paragraphs = content.split("\n\n")
                html_content = "".join(
                    f"<p>{p.replace(chr(10), '<br>')}</p>"
                    for p in paragraphs if p.strip()
                )
                # 用 JS 直接操作 ProseMirror DOM + 触发事件
                inject_js = (
                    "var ed = arguments[0];"
                    "ed.innerHTML = arguments[1];"
                    "ed.dispatchEvent(new Event('input', {bubbles: true, composed: true}));"
                    "ed.dispatchEvent(new Event('change', {bubbles: true}));"
                    "ed.dispatchEvent(new Event('blur', {bubbles: true}));"
                    "ed.dispatchEvent(new Event('focus', {bubbles: true}));"
                    # 触发 ProseMirror 能感知的 beforeinput/compositionend
                    "ed.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}));"
                    "ed.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true, data: arguments[1]}));"
                    "ed.dispatchEvent(new InputEvent('beforeinput', {bubbles: true, inputType: 'insertText', data: 'x'}));"
                    "ed.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText'}));"
                )
                self.driver.execute_script(inject_js, body_editor, html_content)
                log.info(f"  正文已注入 ({len(content)} 字)")
                self._sleep(1)
            else:
                log.error("未找到正文编辑器")
            self._sleep(2)

            # ---- 点击「下一步」 ----
            if not self._click_button(["下一步"]):
                log.error("点击「下一步」失败")
                return False
            self._sleep(3)

            # ===== 点击「下一步」后的弹窗序列 =====
            # 序列：错别字弹窗（如有）→ 检测选择 → 全面检测 → 加载 → 发布设置
            log.info("等待下一步后的弹窗...")
            self._sleep(1.5)

            # 1. 处理错别字弹窗——如果出现了就点「提交」
            self._click_button(["提交", "仍然发布", "继续", "忽略并提交"])
            self._sleep(1.5)

            # 2. 处理内容检测选择弹窗——点「全面检测」
            self._click_button(["全面检测", "全面检查", "仅基础检测", "内容检测"])
            self._sleep(1.5)

            # 3. 等待检测完成 + 「发布设置」弹窗出现
            log.info("等待内容检测完成...")
            self._wait_for_button(["确认发布", "发布设置"], timeout_sec=60)
            self.driver.save_screenshot(str(LOG_DIR / "debug" / f"final_{chapter_num}.png"))
            final_visible = self._wait_for_button(["确认发布", "发布", "提交"], timeout_sec=10)
            log.info(f"  发布设置弹窗按钮: {final_visible}")

            # 在「发布设置」弹窗中处理「是否使用AI」字段
            # 番茄的「是否使用AI」可能是一个 switch/toggle、radio 组、或 select 下拉
            ai_set = False

            # 方式1：查找包含"AI"/"使用AI"文字的父容器，在其中找可点击选项
            ai_labels = self.driver.find_elements(By.XPATH,
                "//*[contains(text(),'AI') or contains(text(),'人工智能') or contains(text(),'使用')]")
            for label in ai_labels:
                try:
                    if not label.is_displayed():
                        continue
                    txt = label.text or ""
                    if "AI" in txt or "人工智能" in txt:
                        # 在旁边找"是"的 radio/label/button
                        parent = label.find_element(By.XPATH, "..")
                        if parent:
                            yes_els = parent.find_elements(By.XPATH,
                                ".//*[contains(text(),'是') and not(contains(text(),'否'))]")
                            for y in yes_els:
                                try:
                                    if y.is_displayed() and y.tag_name in ("label", "span", "div", "input"):
                                        self.driver.execute_script("arguments[0].click();", y)
                                        ai_set = True
                                        log.info("  AI 声明已勾选「是」")
                                        break
                                except Exception:
                                    pass
                        if ai_set:
                            break
                except Exception:
                    pass

            # 方式2：直接遍历可点击元素找「是」
            if not ai_set:
                yes_candidates = self.driver.find_elements(By.XPATH,
                    "//*[text()='是' and (self::label or self::span or self::div or self::input)]")
                for y in yes_candidates:
                    try:
                        if y.is_displayed():
                            self.driver.execute_script("arguments[0].click();", y)
                            ai_set = True
                            log.info("  AI 声明已勾选 (fallback)")
                            self._sleep(0.3)
                            break
                    except Exception:
                        pass

            # 点击「确认发布」
            if not self._click_button(["确认发布", "发布", "确认", "提交", "保存并发布"]):
                log.error("点击「确认发布」失败，可见按钮: " + str(final_visible))
                return False
            self._sleep(2)

            log.info(f"✓ 第{chapter_num}章《{title}》发布完成")
            return True

        except Exception as e:
            log.error(f"发布第{chapter_num}章时出错: {e}")
            return False

    def _paste_via_clipboard(self, text: str) -> bool:
        """通过系统剪贴板粘贴文本，触发完整键盘事件链。失败返回 False"""
        try:
            import subprocess, tempfile
            from selenium.webdriver.common.keys import Keys

            # macOS: pbcopy
            proc = subprocess.run(
                ["pbcopy"], input=text.encode("utf-8"), check=True)
            # Cmd+V
            body = self.driver.find_element("tag name", "body")
            body.send_keys(Keys.COMMAND, "v")
            self._sleep(1)
            return True
        except Exception:
            try:
                import pyperclip
                pyperclip.copy(text)
                body = self.driver.find_element("tag name", "body")
                body.send_keys(Keys.COMMAND, "v")
                self._sleep(1)
                return True
            except Exception:
                return False


# ============================================================
# 主控制流
# ============================================================

def load_config(project: str = "") -> dict:
    config_file = CONFIG_DIR / "发布配置.yaml"
    if project:
        project_config = CONFIG_DIR / f"发布配置-{project}.yaml"
        if project_config.exists():
            config_file = project_config
        else:
            log.warning(f"未找到项目配置 {project_config.name}，使用默认配置")
    if not config_file.exists():
        log.error(f"配置文件不存在: {config_file}")
        sys.exit(1)
    log.info(f"加载配置: {config_file.name}")
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_chapters_to_publish(config: dict, args) -> List[Tuple[int, str, Path]]:
    all_chapters = discover_chapters()
    if not all_chapters:
        log.warning("未发现任何章节文件")
        return []

    strategy = config.get("发布策略", {})
    # --chapter 自动切换为单章模式
    if args.chapter and not args.mode:
        mode = "单章"
    else:
        mode = args.mode or strategy.get("模式", "增量")
    published_history = load_published_history()

    if mode == "单章":
        target = args.chapter or strategy.get("指定章节")
        if target:
            n = int(target) if isinstance(target, str) and target.isdigit() else target
            return [(num, title, path) for num, title, path in all_chapters if num == n]
        return []
    elif mode == "批量":
        start = args.start or strategy.get("起始章节", 1)
        end = args.end or strategy.get("结束章节", len(all_chapters))
        return [(num, title, path) for num, title, path in all_chapters if start <= num <= end]
    elif mode == "增量":
        return [(num, title, path) for num, title, path in all_chapters if num not in published_history]
    return all_chapters


def main():
    global CHAPTERS_DIR, CURRENT_PROJECT_NAME
    parser = argparse.ArgumentParser(description="番茄小说章节自动发布器")
    parser.add_argument("--chapter", type=int, help="发布指定章节")
    parser.add_argument("--start", type=int, help="批量发布起始章节")
    parser.add_argument("--end", type=int, help="批量发布结束章节")
    parser.add_argument("--mode", choices=["单章", "批量", "增量"], help="发布模式")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际发布")
    parser.add_argument("--keep-open", action="store_true", help="出错或完成后不关闭浏览器")
    parser.add_argument("--project", type=str, default="",
        help="项目名。加载 发布配置-{项目名}.yaml，如 --project 万古神龙")
    args = parser.parse_args()

    config = load_config(project=args.project)
    # 设置全局项目名，用于隔离已发布记录和各项目的 Chrome profile
    book_name = config.get("作品", {}).get("书名", "")
    CURRENT_PROJECT_NAME = args.project or book_name or "default"
    log.info(f"当前项目: {CURRENT_PROJECT_NAME}")
    # 从配置中解析小说目录
    novel_dir = config.get("作品", {}).get("小说目录", "")
    if novel_dir:
        novel_path = Path(novel_dir)
        if not novel_path.is_absolute():
            novel_path = PROJECT_ROOT / novel_path
        CHAPTERS_DIR = novel_path / "执行" / "章节"
    else:
        # 兼容旧配置：按书名找小说目录
        book_name = config.get("作品", {}).get("书名", "")
        if book_name:
            CHAPTERS_DIR = PROJECT_ROOT / book_name / "执行" / "章节"
        else:
            CHAPTERS_DIR = PROJECT_ROOT / "执行" / "章节"
    log.info(f"章节目录: {CHAPTERS_DIR}")
    chapters = get_chapters_to_publish(config, args)

    if not chapters:
        log.info("没有需要发布的章节")
        return

    print("\n" + "=" * 60)
    print("  番 茄 小 说 自 动 发 布 器")
    print("=" * 60)
    print(f"  作品: {config.get('作品', {}).get('书名', '未配置')}")
    print(f"  模式: {args.mode or config.get('发布策略', {}).get('模式', '增量')}")
    print(f"  待发布: {len(chapters)} 章")
    print(f"  章节范围: 第{chapters[0][0]}章 ~ 第{chapters[-1][0]}章")
    print(f"  错别字提醒: {'自动忽略' if config.get('发布行为', {}).get('自动忽略错别字提醒', True) else '手动处理'}")
    print("=" * 60 + "\n")

    if args.dry_run:
        print("[预览模式] 以下章节将被发布:")
        for num, title, path in chapters:
            print(f"  第{num}章 · {title}  ({len(read_chapter_content(path))} 字)")
        print("\n未执行实际发布。")
        return

    publisher = FanqiePublisher(config)
    success_count = 0
    try:
        publisher.start()
        # 不再调用 login()——假设用户已在 Chrome 中登录
        # 直接导航到目标作品
        if not publisher.navigate_to_work():
            log.error("无法定位作品，请确认已在浏览器中登录并正确配置作品信息")
            if args.keep_open:
                input("\n按 Enter 关闭浏览器...")
            return

        for num, title, path in chapters:
            content = read_chapter_content(path)
            if publisher.publish_chapter(num, title, content):
                save_published_history(num, title)
                success_count += 1
            publisher._sleep(1.5)

        print(f"\n发布完成: {success_count}/{len(chapters)} 章成功")

    except KeyboardInterrupt:
        log.warning("用户中断")
    except Exception as e:
        log.error(f"发布过程异常: {e}")
    finally:
        if args.keep_open:
            print("\n浏览器保持打开，方便排查。按 Enter 关闭...")
            input()
        publisher.quit()


if __name__ == "__main__":
    main()
