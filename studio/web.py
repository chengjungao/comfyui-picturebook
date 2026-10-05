"""本地 Web 服务：界面 + 接口。

为什么用标准库的 http.server 而不是 Flask：读者解压完直接双击就能用，
不用 pip install，也不会跟 ComfyUI 那边的 Python 环境打架。

出图是长任务，所以拆成两半：
- `POST /api/...` 只负责**把任务丢进后台线程**，立刻返回；
- 前端每 1.5 秒拉一次 `GET /api/progress` 拿进度。
长连接（SSE/WebSocket）在这种「几十秒到几分钟一次」的场景没有收益，
轮询更简单也更不容易出问题。
"""
import json
import mimetypes
import os
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import bookbuild
from . import pdf as pdfmod
from . import project as P
from .comfy import ComfyError
from .pipeline import Canceled, Generator

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

MAX_BODY = 256 * 1024 * 1024


class State(object):
    """界面要看的运行状态。所有写入都在锁里，避免两个请求撞上。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.running = False
        self.stage = ""
        self.msg = ""
        self.started = 0.0
        self.elapsed = 0.0
        self.queue = {"running": 0, "pending": 0}
        self.jobs = {}
        self.total = 0
        self.done = 0
        self.log = []
        self.result = None

    def add_log(self, text):
        with self.lock:
            self.log.append("[%s] %s" % (time.strftime("%H:%M:%S"), text))
            self.log = self.log[-120:]

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running, "stage": self.stage, "msg": self.msg,
                "elapsed": round(self.elapsed, 1), "queue": dict(self.queue),
                "jobs": {k: dict(v) for k, v in self.jobs.items()},
                "total": self.total, "done": self.done,
                "log": list(self.log), "result": self.result,
            }


class App(object):
    def __init__(self, cfg, folder):
        self.cfg = cfg
        self.folder = os.path.abspath(folder)
        self.state = State()
        self.gen = None
        self.thread = None
        self._lock = threading.Lock()

    # ---------- 任务 ----------

    def _ensure_gen(self):
        if self.gen is None:
            self.gen = Generator(self.cfg, self.folder, on_event=self._on_event)
        else:
            self.gen.cfg = self.cfg
        return self.gen

    def _on_event(self, evt):
        st = self.state
        t = evt.get("type")
        with st.lock:
            if t == "stage":
                st.stage = evt.get("stage", "")
                st.msg = evt.get("msg", "")
            elif t == "submit":
                pid = evt.get("id")
                if pid:
                    st.jobs[pid] = {"status": "queued", "msg": ""}
                    st.done = evt.get("done", st.done)
                    st.total = evt.get("total", st.total)
            elif t == "page_done":
                item = evt.get("item") or {}
                st.jobs[item.get("id", "?")] = {
                    "status": "done" if item.get("ok") else "failed",
                    "msg": item.get("msg", ""),
                    "elapsed": item.get("elapsed")}
            elif t == "done":
                st.jobs[evt.get("id", "?")] = {"status": "done", "msg": ""}
                st.msg = "已完成"
            elif t == "failed":
                st.jobs[evt.get("id", "?")] = {"status": "failed",
                                               "msg": evt.get("msg", "")}
                st.msg = evt.get("msg", "出错了")
            elif t == "tick":
                st.elapsed = evt.get("elapsed", st.elapsed)
                st.queue = {"running": evt.get("running", 0),
                            "pending": evt.get("pending", 0)}
            elif t == "stage_done":
                st.result = {"stage": evt.get("stage"),
                             "elapsed": evt.get("elapsed"),
                             "results": evt.get("results", [])}

    def start_job(self, fn, name):
        with self._lock:
            if self.state.running:
                return False, "已经有一个任务在跑，等它结束或先点取消。"
            self.state.reset()
            self.state.running = True
            self.state.stage = name
            self.state.started = time.time()
            gen = self._ensure_gen()
            gen.reset_cancel()

        def runner():
            try:
                fn(gen)
                self.state.add_log("任务完成：" + name)
            except Canceled:
                self.state.add_log("任务已取消：" + name)
            except (ComfyError, ValueError, OSError) as e:
                self.state.add_log("出错：" + str(e))
                with self.state.lock:
                    self.state.msg = str(e)
            except Exception as e:                       # 兜底，别让线程静默死掉
                import traceback
                self.state.add_log("意外错误：" + str(e))
                traceback.print_exc()
                with self.state.lock:
                    self.state.msg = "意外错误：%s" % e
            finally:
                with self.state.lock:
                    self.state.running = False
                    self.state.stage = ""
                    self.state.elapsed = round(time.time() - self.state.started, 1)

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()
        return True, "已开始：" + name

    def cancel(self):
        if self.gen:
            self.gen.cancel()
        return True, "已请求取消"


def _find_free_port(preferred=8765):
    for port in range(preferred, preferred + 20):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return preferred


class Handler(BaseHTTPRequestHandler):
    app = None
    server_version = "PictureBookStudio"

    def log_message(self, fmt, *args):        # 静音访问日志，控制台只留我们的输出
        pass

    # ---------- 基础 ----------

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _file(self, path, ctype=None):
        if not os.path.exists(path):
            return self._send(404, {"error": "找不到文件：%s" % os.path.basename(path)})
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > MAX_BODY:
            raise ValueError("请求太大")
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("请求体不是合法 JSON")

    # ---------- 路由 ----------

    def do_GET(self):
        p = urlparse(self.path).path
        app = self.app
        try:
            if p in ("/", "/index.html"):
                return self._file(os.path.join(WEB_DIR, "index.html"))
            if p.startswith("/static/"):
                name = os.path.basename(unquote(p[len("/static/"):]))
                return self._file(os.path.join(WEB_DIR, name))
            if p.startswith("/img/"):
                name = os.path.basename(unquote(p[len("/img/"):]))
                return self._file(os.path.join(P.img_dir(app.folder), name), "image/png")
            if p == "/book":
                return self._file(os.path.join(app.folder, "book.html"), "text/html")
            if p == "/api/state":
                return self._send(200, self._state())
            if p == "/api/progress":
                return self._send(200, app.state.snapshot())
            if p == "/api/health":
                return self._send(200, self._health())
            if p == "/api/models":
                return self._send(200, self._models())
            return self._send(404, {"error": "没有这个接口：%s" % p})
        except ComfyError as e:
            return self._send(200, {"ok": False, "error": str(e)})
        except Exception as e:
            return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    def do_POST(self):
        p = urlparse(self.path).path
        app = self.app
        try:
            body = self._body()
            if p == "/api/project":
                return self._save_project(body)
            if p == "/api/config":
                return self._save_config(body)
            if p == "/api/key":
                return self._key(body)
            if p == "/api/pages":
                return self._pages(body)
            if p == "/api/one":
                return self._one(body)
            if p == "/api/cancel":
                ok, msg = app.cancel()
                return self._send(200, {"ok": ok, "msg": msg})
            if p == "/api/build":
                return self._build()
            if p == "/api/pdf":
                return self._pdf()
            if p == "/api/import-key":
                return self._import_key(body)
            if p == "/api/new":
                return self._new_project(body)
            if p == "/api/open":
                return self._open(body)
            return self._send(404, {"error": "没有这个接口：%s" % p})
        except (ComfyError, ValueError, OSError) as e:
            return self._send(200, {"ok": False, "error": str(e)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    # ---------- 数据 ----------

    def _state(self):
        app = self.app
        data = P.load(app.folder)
        issues = P.validate(data) if data else [("error", "这个文件夹里还没有工程文件")]
        return {
            "ok": True,
            "folder": app.folder,
            "config": app.cfg,
            "project": data,
            "stats": P.stats(data) if data else None,
            "issues": issues,
            "images": self._image_list(),
            "has_key": os.path.exists(os.path.join(P.img_dir(app.folder), P.REF_NAME)),
            "has_html": os.path.exists(os.path.join(app.folder, "book.html")),
            "pdf": self._pdf_path(),
        }

    def _image_list(self):
        d = P.img_dir(self.app.folder)
        if not os.path.isdir(d):
            return []
        return sorted(f for f in os.listdir(d) if f.lower().endswith((".png", ".jpg")))

    def _pdf_path(self):
        data = P.load(self.app.folder) or {}
        title = (data.get("title") or "我的绘本").strip()
        path = os.path.join(self.app.folder, title + ".pdf")
        if os.path.exists(path):
            return {"path": path, "size_mb": round(os.path.getsize(path) / 1048576, 1)}
        return None

    def _health(self):
        return self.app._ensure_gen().health()

    def _models(self):
        try:
            return {"ok": True, **self.app._ensure_gen().model_choices()}
        except ComfyError as e:
            return {"ok": False, "error": str(e)}

    # ---------- 动作 ----------

    def _save_project(self, body):
        data = body.get("project")
        if not isinstance(data, dict):
            raise ValueError("project 字段不对")
        P.save(self.app.folder, data)
        return self._send(200, {"ok": True, "msg": "已保存",
                                "issues": P.validate(data),
                                "stats": P.stats(data)})

    def _save_config(self, body):
        cfg = body.get("config")
        if not isinstance(cfg, dict):
            raise ValueError("config 字段不对")
        from . import config as cfgmod
        self.app.cfg = cfgmod.save_and_reload(cfg)
        if self.app.gen:
            self.app.gen.cfg = self.app.cfg
        return self._send(200, {"ok": True, "msg": "设置已保存", "config": self.app.cfg})

    def _new_project(self, body):
        title = (body.get("title") or "我的绘本").strip()
        if P.load(self.app.folder) and not body.get("overwrite"):
            return self._send(200, {"ok": False, "error": "已经有工程文件了"})
        P.save(self.app.folder, P.new(title))
        return self._send(200, {"ok": True, "msg": "已新建工程"})

    def _key(self, body):
        prompt = (body.get("prompt") or "").strip()
        ok, msg = self.app.start_job(lambda g: g.make_key(prompt or None), "角色定妆照")
        return self._send(200, {"ok": ok, "msg": msg})

    def _pages(self, body):
        ids = body.get("ids") or None
        ok, msg = self.app.start_job(lambda g: g.make_pages(ids), "批量出图")
        return self._send(200, {"ok": ok, "msg": msg})

    def _one(self, body):
        pid = body.get("id")
        if not pid:
            raise ValueError("缺少 id")
        ok, msg = self.app.start_job(lambda g: g.make_one(pid), "重出 " + pid)
        return self._send(200, {"ok": ok, "msg": msg})

    def _build(self):
        path, info = bookbuild.build(self.app.folder, self.app.cfg)
        return self._send(200, {"ok": True, "msg": "排版完成", "path": path, "info": info})

    def _pdf(self):
        out, info = bookbuild.build(self.app.folder, self.app.cfg)
        data = P.load(self.app.folder) or {}
        title = (data.get("title") or "我的绘本").strip()
        target = os.path.join(self.app.folder, title + ".pdf")
        ok, msg = pdfmod.to_pdf(out, target, self.app.cfg.get("browser_path", ""))
        if not ok:
            return self._send(200, {"ok": False, "error": msg})
        return self._send(200, {"ok": True, "msg": "PDF 已生成", "path": target,
                                "size_mb": round(os.path.getsize(target) / 1048576, 1),
                                "pages": info["pages"]})

    def _import_key(self, body):
        raw = body.get("data") or ""
        if "," in raw:
            raw = raw.split(",", 1)[1]
        import base64
        try:
            content = base64.b64decode(raw)
        except Exception:
            raise ValueError("图片数据解析失败")
        if len(content) < 1000:
            raise ValueError("这张图好像没传全，换一张试试")
        self.app._ensure_gen().import_key_image(content)
        return self._send(200, {"ok": True, "msg": "定妆照已导入"})

    def _open(self, body):
        what = body.get("what") or "folder"
        if what == "pdf":
            info = self._pdf_path()
            path = info["path"] if info else None
        elif what == "html":
            path = os.path.join(self.app.folder, "book.html")
        else:
            path = self.app.folder
        if not path or not os.path.exists(path):
            return self._send(200, {"ok": False, "error": "还没生成，先点一下对应的按钮"})
        try:
            if os.name == "nt":
                os.startfile(path)                      # noqa: S606
            elif sys_platform() == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
            return self._send(200, {"ok": True, "msg": "已打开"})
        except Exception as e:
            return self._send(200, {"ok": False, "error": "打不开：%s" % e})


def sys_platform():
    import sys
    return sys.platform


def run(cfg, folder, port=None, open_browser=True):
    Handler.app = App(cfg, folder)
    port = port or _find_free_port(8765)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("")
    print("  绘本工坊已启动：%s" % url)
    print("  工程目录：%s" % os.path.abspath(folder))
    print("  关掉这个窗口就停止。")
    print("")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return port
