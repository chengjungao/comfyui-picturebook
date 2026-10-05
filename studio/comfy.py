"""ComfyUI 客户端。

只用标准库。三个必须做对的地方：

1. **绕过本机代理。** 如果系统设了 HTTP_PROXY，访问 127.0.0.1 会被代理拦下，
   表现为 502，很容易误判成「ComfyUI 没启动」。所以所有请求都走一个空代理的 opener。
2. **参考图用 HTTP 上传**，不去直接写 ComfyUI 的 input 目录 ——
   这样 ComfyUI 装在另一台机器上也能用，读者不需要知道 ComfyUI 装在哪。
3. **提交前先看 node_errors**，别等轮询半天才发现节点校验就没过。
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

# 空代理 opener：绕开系统代理对回环地址的拦截
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ComfyError(Exception):
    """带用户可读原因的 ComfyUI 调用错误。"""


class Comfy(object):
    def __init__(self, base_url="http://127.0.0.1:8188", timeout=60):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    # ---------- 底层 ----------

    def _open(self, req, timeout=None):
        try:
            return _OPENER.open(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            raise ComfyError(self._explain(e.code, body))
        except urllib.error.URLError as e:
            raise ComfyError(
                "连不上 ComfyUI（%s）。请确认 ComfyUI 已经启动，"
                "并且地址填对了：%s" % (getattr(e, "reason", e), self.base))
        except Exception as e:
            raise ComfyError("请求失败：%s" % e)

    @staticmethod
    def _explain(code, body):
        if code == 502:
            return ("ComfyUI 返回 502。这通常是本机代理拦截了回环请求，"
                    "已经自动绕过；如果仍出现，请确认 ComfyUI 进程还在。")
        try:
            j = json.loads(body)
            msg = j.get("error") or j
            return "ComfyUI 返回 %s：%s" % (code, json.dumps(msg, ensure_ascii=False)[:600])
        except Exception:
            return "ComfyUI 返回 %s：%s" % (code, body[:600])

    def get(self, path, timeout=None):
        req = urllib.request.Request(self.base + path)
        return json.load(self._open(req, timeout))

    def get_bytes(self, path, timeout=None):
        req = urllib.request.Request(self.base + path)
        return self._open(req, timeout).read()

    def post_json(self, path, payload, timeout=None):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        return json.load(self._open(req, timeout))

    def post_multipart(self, path, fields, files, timeout=None):
        """files: {字段名: (文件名, 字节)}"""
        boundary = "----PictureBook" + uuid.uuid4().hex
        buf = []
        for k, v in fields.items():
            buf.append(("--%s\r\n" % boundary).encode("utf-8"))
            buf.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode("utf-8"))
            buf.append(str(v).encode("utf-8") + b"\r\n")
        for k, (fname, content) in files.items():
            buf.append(("--%s\r\n" % boundary).encode("utf-8"))
            buf.append(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                        % (k, fname)).encode("utf-8"))
            buf.append(b"Content-Type: application/octet-stream\r\n\r\n")
            buf.append(content + b"\r\n")
        buf.append(("--%s--\r\n" % boundary).encode("utf-8"))
        body = b"".join(buf)
        req = urllib.request.Request(self.base + path, data=body, headers={
            "Content-Type": "multipart/form-data; boundary=%s" % boundary})
        return json.load(self._open(req, timeout))

    # ---------- 业务 ----------

    def system_stats(self):
        return self.get("/system_stats", timeout=15)

    def queue(self):
        return self.get("/queue", timeout=15)

    def object_info(self):
        return self.get("/object_info", timeout=180)

    def health(self):
        """返回一份给界面看的体检报告。"""
        rep = {"ok": False, "url": self.base, "errors": [], "warnings": [], "info": {}}
        try:
            st = self.system_stats()
        except ComfyError as e:
            rep["errors"].append(str(e))
            return rep

        sysinfo = (st.get("system") or {})
        rep["info"]["comfyui_version"] = sysinfo.get("comfyui_version", "?")
        rep["info"]["python"] = sysinfo.get("python_version", "?")
        for d in st.get("devices") or []:
            rep["info"]["device"] = d.get("name", "?")
            total = d.get("vram_total") or 0
            free = d.get("vram_free") or 0
            if total:
                rep["info"]["vram_total_gb"] = round(total / 1073741824, 1)
                rep["info"]["vram_free_gb"] = round(free / 1073741824, 1)
            if "cpu" in str(d.get("type", "")).lower():
                rep["warnings"].append(
                    "ComfyUI 当前跑在 CPU 上，出图会很慢。请装带 CUDA 的版本。")
        try:
            q = self.queue()
            rep["info"]["queue_running"] = len(q.get("queue_running") or [])
            rep["info"]["queue_pending"] = len(q.get("queue_pending") or [])
        except ComfyError:
            pass
        rep["ok"] = True
        return rep

    def list_model_choices(self):
        """从 /object_info 读运行中 ComfyUI 实际认识的模型文件名。

        比让读者手抄文件名可靠 —— 目录里有不等于被识别。
        """
        oi = self.object_info()

        def opts(node, field):
            try:
                spec = oi[node]["input"]
                for group in ("required", "optional"):
                    f = (spec.get(group) or {}).get(field)
                    if f and isinstance(f[0], list):
                        return list(f[0])
            except Exception:
                pass
            return []

        return {
            "unet": opts("UNETLoader", "unet_name"),
            "clip": opts("CLIPLoader", "clip_name"),
            "vae": opts("VAELoader", "vae_name"),
            "has_qwen_nodes": "TextEncodeQwenImage21" in oi,
        }

    def upload_image(self, local_path, name=None):
        """上传参考图到 ComfyUI 的 input 区，返回它认的文件名。"""
        name = name or os.path.basename(local_path)
        with open(local_path, "rb") as f:
            content = f.read()
        res = self.post_multipart("/upload/image", {"overwrite": "true"},
                                  {"image": (name, content)}, timeout=120)
        nm = res.get("name", name)
        sub = res.get("subfolder") or ""
        return (sub + "/" + nm) if sub else nm

    def submit(self, api_workflow):
        res = self.post_json("/prompt", {"prompt": api_workflow, "client_id": "picturebook"})
        errs = res.get("node_errors") or {}
        if errs:
            raise ComfyError("工作流校验没过：%s"
                             % json.dumps(errs, ensure_ascii=False)[:800])
        pid = res.get("prompt_id")
        if not pid:
            raise ComfyError("ComfyUI 没有返回任务号：%s" % res)
        return pid

    def history(self, prompt_id):
        h = self.get("/history/" + prompt_id, timeout=30)
        return h.get(prompt_id)

    def wait(self, prompt_id, timeout=3600, poll=2.0, on_tick=None, should_stop=None):
        """轮询到出图完成。返回 (是否成功, 图片列表, 错误消息)。"""
        t0 = time.time()
        while True:
            if should_stop and should_stop():
                return False, [], "已取消"
            entry = self.history(prompt_id)
            if entry is not None:
                st = entry.get("status") or {}
                ok = st.get("status_str") == "success"
                images = []
                for _nid, out in (entry.get("outputs") or {}).items():
                    for im in out.get("images") or []:
                        images.append({"filename": im.get("filename"),
                                       "subfolder": im.get("subfolder") or "",
                                       "type": im.get("type") or "output"})
                if ok:
                    return True, images, ""
                msgs = []
                for m in st.get("messages") or []:
                    msgs.append(json.dumps(m, ensure_ascii=False)[:300])
                return False, images, "出图失败：" + " | ".join(msgs[:3])
            if on_tick:
                elapsed = time.time() - t0
                running = pending = 0
                try:
                    q = self.queue()
                    running = len(q.get("queue_running") or [])
                    pending = len(q.get("queue_pending") or [])
                except ComfyError:
                    pass
                on_tick(elapsed, running, pending)
            if time.time() - t0 > timeout:
                return False, [], "超时（超过 %d 分钟还没出图）" % (timeout // 60)
            time.sleep(poll)

    def fetch_image(self, filename, subfolder="", type_="output"):
        """取回图片字节。不读本地磁盘，因此 ComfyUI 在别的机器上也成立。"""
        from urllib.parse import urlencode
        qs = urlencode({"filename": filename, "subfolder": subfolder, "type": type_})
        return self.get_bytes("/view?" + qs, timeout=180)
