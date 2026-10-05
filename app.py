"""绘本工坊 —— 启动入口。

    python app.py                     启动界面（工程目录默认 ./我的绘本）
    python app.py --folder 我的绘本     指定工程目录
    python app.py --port 9000         指定端口
    python app.py --check             不开界面，只做一次环境自检
    python app.py --example           把示例绘本复制成一份新工程

依赖：只有 Python 标准库。ComfyUI 需要另外装好并在运行。
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from studio import config as cfgmod          # noqa: E402
from studio import pdf as pdfmod             # noqa: E402
from studio import project as P              # noqa: E402
from studio.comfy import Comfy, ComfyError   # noqa: E402

DEFAULT_FOLDER = "我的绘本"
EXAMPLE_DIR = os.path.join(HERE, "examples", "小狐狸的秋日远行")


def _setup_console():
    """Windows 控制台默认不是 UTF-8，中文会变乱码。"""
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def cmd_check(cfg):
    print("=" * 56)
    print("  环境自检")
    print("=" * 56)
    print("  Python      : %s" % sys.version.split()[0])
    print("  配置文件    : %s" % cfgmod.CONFIG_PATH)

    br = pdfmod.find_browser(cfg.get("browser_path", ""))
    print("  浏览器      : %s" % (br or "没找到（无法自动转 PDF，仍可手动打印）"))

    url = cfg["comfy_url"]
    print("  ComfyUI     : %s" % url)
    c = Comfy(url, timeout=20)
    try:
        rep = c.health()
    except ComfyError as e:
        print("    连不上：%s" % e)
        return 1
    if not rep["ok"]:
        for e in rep["errors"]:
            print("    ✗ %s" % e)
        return 1
    info = rep["info"]
    print("    ✓ 已连通（ComfyUI %s / Python %s）"
          % (info.get("comfyui_version"), info.get("python")))
    if info.get("device"):
        print("    显卡：%s  显存 %.1f GB（空闲 %.1f GB）"
              % (info["device"], info.get("vram_total_gb", 0),
                 info.get("vram_free_gb", 0)))
    print("    队列：执行中 %s / 等待 %s"
          % (info.get("queue_running"), info.get("queue_pending")))
    for w in rep["warnings"]:
        print("    ! %s" % w)

    try:
        m = c.list_model_choices()
    except ComfyError as e:
        print("    读模型清单失败：%s" % e)
        return 1

    print("  模型        :")
    if not m.get("has_qwen_nodes"):
        print("    ✗ 没找到 Qwen-Image 的节点。这个工作流需要 ComfyUI 支持 "
              "TextEncodeQwenImage21（较新的版本自带）。")
    names = {"unet": cfg["models"]["unet"], "clip": cfg["models"]["clip"],
             "vae": cfg["models"]["vae"]}
    ok = m.get("has_qwen_nodes", False)
    for k, label in (("unet", "扩散模型"), ("clip", "文本编码器"), ("vae", "VAE")):
        avail = m.get(k) or []
        if names[k] in avail:
            print("    ✓ %s：%s" % (label, names[k]))
        else:
            ok = False
            print("    ✗ %s 里没有 %s" % (label, names[k]))
            if avail:
                print("      实际可选（把 config.json 里的名字换成其中一个）：")
                for a in avail[:8]:
                    print("        - %s" % a)
            else:
                print("      这是空的，说明这类模型一个都没装。")
    print("=" * 56)
    print("  结论：%s" % ("环境就绪，可以启动界面了。" if ok
                         else "还差东西，按上面的 ✗ 补齐后再跑一次 --check。"))
    return 0 if ok else 1


def cmd_example(folder):
    if not os.path.isdir(EXAMPLE_DIR):
        print("示例目录不存在：%s" % EXAMPLE_DIR)
        return 1
    if os.path.exists(os.path.join(folder, P.PROJECT_NAME)):
        print("「%s」里已经有工程了，换个目录名再试。" % folder)
        return 1
    shutil.copytree(EXAMPLE_DIR, folder)
    print("示例已复制到：%s" % os.path.abspath(folder))
    print("（提示：示例里只有分镜与正文，插图要用你自己的定妆照重新出。）")
    return 0


def main():
    _setup_console()
    ap = argparse.ArgumentParser(description="绘本工坊：用本地 ComfyUI 做一本绘本")
    ap.add_argument("--folder", default=DEFAULT_FOLDER, help="工程目录")
    ap.add_argument("--port", type=int, default=0, help="服务端口（默认自动挑一个）")
    ap.add_argument("--check", action="store_true", help="只做环境自检")
    ap.add_argument("--example", action="store_true", help="复制示例工程")
    ap.add_argument("--no-browser", action="store_true", help="不要自动打开浏览器")
    args = ap.parse_args()

    cfg = cfgmod.load()

    if args.check:
        return cmd_check(cfg)

    if args.example:
        return cmd_example(os.path.abspath(args.folder))

    folder = os.path.abspath(args.folder)
    if not P.load(folder):
        # 首次运行：建一个三页的空工程，让读者直接开始填
        P.save(folder, P.new())
        print("已新建工程：%s" % os.path.join(folder, P.PROJECT_NAME))
        if os.path.isdir(EXAMPLE_DIR):
            print("（examples/ 里有一份写好的示例，想看长什么样可以复制过去）")

    from studio import web
    web.run(cfg, folder, port=args.port or None,
            open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
