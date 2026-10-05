"""把 book.html 转成 PDF。

用的是「无头浏览器打印」这条路，而不是装一个 PDF 库 —— 因为：

- 零依赖。读者不用为生成 PDF 再装任何东西。
- 版式所见即所得。排版就是 CSS，浏览器打印和屏幕上看到的一致；
  换成 PDF 库反而要重新实现一遍分页与字体。

找不到浏览器时不报错退出，而是告诉读者怎么手动存成 PDF（打开 HTML → 打印 → 存为 PDF），
这条路在任何机器上都成立。
"""
import os
import shutil
import subprocess
import sys

WIN_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
MAC_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
LINUX_NAMES = ["google-chrome", "google-chrome-stable", "chromium",
               "chromium-browser", "microsoft-edge"]


def find_browser(hint=""):
    """返回可用的浏览器可执行文件路径，找不到返回 None。"""
    if hint and os.path.exists(hint):
        return hint
    if sys.platform.startswith("win"):
        for p in WIN_CANDIDATES:
            if os.path.exists(p):
                return p
        for p in (os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                  os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")):
            if os.path.exists(p):
                return p
    elif sys.platform == "darwin":
        for p in MAC_CANDIDATES:
            if os.path.exists(p):
                return p
    else:
        for n in LINUX_NAMES:
            w = shutil.which(n)
            if w:
                return w
    return None


def to_pdf(html_path, pdf_path, browser_hint=""):
    """返回 (是否成功, 消息)。"""
    html_path = os.path.abspath(html_path)
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.exists(html_path):
        return False, "找不到 %s，请先点「排版」生成 HTML。" % html_path

    br = find_browser(browser_hint)
    if not br:
        return False, (
            "没找到 Chrome 或 Edge，无法自动转 PDF。\n"
            "两条路都行：\n"
            "  ① 装一个 Chrome 或 Edge（装了就能自动转）；\n"
            "  ② 手动转：双击打开 %s，按 Ctrl+P，目标选「另存为 PDF」，\n"
            "     纸张尺寸选「自定义」、方向「横向」、边距「无」，保存即可。"
            % html_path)

    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except OSError:
            pass

    from pathlib import Path
    url = Path(html_path).as_uri()
    base = [br, "--disable-gpu", "--no-sandbox", "--no-first-run",
            "--no-pdf-header-footer", "--allow-file-access-from-files",
            "--virtual-time-budget=30000"]

    last = ""
    for headless in ("--headless=new", "--headless"):
        cmd = base + [headless, "--print-to-pdf=" + pdf_path, url]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=180,
                               **_no_window())
            last = (r.stderr or b"").decode("utf-8", "ignore")[-800:]
        except subprocess.TimeoutExpired:
            return False, "浏览器转 PDF 超时（超过 3 分钟）。页面上的图是不是特别多？"
        except Exception as e:
            return False, "调用浏览器失败：%s" % e
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1024:
            return True, pdf_path

    return False, ("浏览器返回了，但没有生成 PDF。\n"
                   "可以手动转：打开 %s → Ctrl+P → 另存为 PDF。\n%s"
                   % (html_path, last.strip()))


def _no_window():
    """Windows 下别弹出黑窗。"""
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si,
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}
