"""出图编排：定妆照 → 批量内页 → 单页重出。

顺序不能跳：**先出一张干净的角色定妆照，人眼看一眼确认，再批量出内页。**
定妆照是全书一致性的唯一来源，它错了，后面每一页都跟着错，而重出十几页很费时间。

批量出图的做法是「一次把全部任务压进队列，再统一轮询」——
让显卡不空转，中间不用管。实测 14 页总计约 351 秒（≈25 秒一张）。
"""
import os
import threading
import time

from . import project as P
from . import workflows as W
from .comfy import Comfy, ComfyError


class Canceled(Exception):
    pass


class Generator(object):
    def __init__(self, cfg, folder, on_event=None):
        self.cfg = cfg
        self.folder = folder
        self.comfy = Comfy(cfg["comfy_url"])
        self.on_event = on_event or (lambda e: None)
        self._stop = threading.Event()

    # ---------- 对外 ----------

    def cancel(self):
        self._stop.set()

    def reset_cancel(self):
        self._stop.clear()

    def health(self):
        return self.comfy.health()

    def model_choices(self):
        return self.comfy.list_model_choices()

    def key_image_exists(self):
        return os.path.exists(os.path.join(P.img_dir(self.folder), P.REF_NAME))

    def import_key_image(self, content, filename="char_sheet.png"):
        """允许读者用自己的图当定妆照（自己画的、或别处出好的都行）。"""
        d = P.img_dir(self.folder)
        if not os.path.isdir(d):
            os.makedirs(d)
        dest = os.path.join(d, P.REF_NAME)
        with open(dest, "wb") as f:
            f.write(content)
        return dest

    def make_key(self, prompt=None):
        """出角色定妆照。"""
        data = P.load(self.folder)
        prompt = (prompt or (data or {}).get("style", {}).get("key_prompt")
                  or W.default_key_prompt())
        gen = self.cfg["generate"]
        seed = int(gen["base_seed"])
        self._emit({"type": "stage", "stage": "key", "msg": "正在生成角色定妆照…"})
        wf = W.build_t2i(self.cfg["models"], gen, prompt, seed, "pb_char_sheet")
        self._run_one("char_sheet", wf, is_key=True)
        return os.path.join(P.img_dir(self.folder), P.REF_NAME)

    def make_pages(self, ids=None):
        """批量出内页。ids 为空则出全部非封面/封底也算 —— 其实全出，封底封面也要图。"""
        data = P.load(self.folder)
        if not data:
            raise ComfyError("还没有工程文件")
        ref_local = os.path.join(P.img_dir(self.folder), P.REF_NAME)
        if not os.path.exists(ref_local):
            raise ComfyError("还没有定妆照。请先生成（或导入）角色定妆照，"
                             "它是全书一致性的来源。")

        self._emit({"type": "stage", "stage": "pages", "msg": "正在上传定妆照…"})
        ref_name = self.comfy.upload_image(ref_local, P.REF_NAME)

        pages = [p for p in data["pages"] if not ids or p["id"] in ids]
        if not pages:
            raise ComfyError("没有要出的页")

        gen = self.cfg["generate"]
        st = data.get("style") or {}
        prefix, suffix = st.get("prefix", ""), st.get("suffix", "")
        base = int(gen["base_seed"])

        all_pages = data["pages"]
        jobs = []
        t0 = time.time()
        for p in pages:
            idx = all_pages.index(p)
            seed = base + 100 + idx
            prompt = W.compose_prompt(prefix, p.get("scene", ""), suffix)
            prefix_name = "pb_" + p["id"].replace("-", "_")
            wf = W.build_i2i(self.cfg["models"], gen, prompt, seed, prefix_name, ref_name)
            pid = self.comfy.submit(wf)
            jobs.append((p["id"], pid, seed))
            self._emit({"type": "submit", "id": p["id"], "seed": seed,
                        "done": len(jobs), "total": len(pages)})
            if self._stop.is_set():
                raise Canceled()

        self._emit({"type": "stage", "stage": "pages",
                    "msg": "共 %d 张已入队，开始等待…" % len(jobs)})
        results = self._wait_all(jobs, t0)
        self._emit({"type": "stage_done", "stage": "pages",
                    "elapsed": round(time.time() - t0, 1), "results": results})
        return results

    def make_one(self, pid):
        """单页重出。不满意就重来，成本很低。"""
        return self.make_pages(ids=[pid])

    # ---------- 内部 ----------

    def _emit(self, evt):
        try:
            self.on_event(evt)
        except Exception:
            pass

    def _run_one(self, key, wf, is_key=False):
        t0 = time.time()
        pid = self.comfy.submit(wf)
        self._emit({"type": "submit", "id": key, "seed": None, "done": 1, "total": 1})

        def tick(elapsed, running, pending):
            self._emit({"type": "tick", "id": key, "elapsed": round(elapsed, 1),
                        "running": running, "pending": pending})

        ok, images, msg = self.comfy.wait(pid, on_tick=tick,
                                          should_stop=self._stop.is_set)
        if not ok:
            self._emit({"type": "failed", "id": key, "msg": msg})
            raise ComfyError(msg)
        self._save(images, key, is_key=is_key)
        self._emit({"type": "done", "id": key, "elapsed": round(time.time() - t0, 1)})

    def _save(self, images, key, is_key=False):
        if not images:
            raise ComfyError("出图成功但没拿到图片，检查工作流里有没有保存节点")
        im = images[0]
        content = self.comfy.fetch_image(im["filename"], im["subfolder"], im["type"])
        d = P.img_dir(self.folder)
        if not os.path.isdir(d):
            os.makedirs(d)
        dest = os.path.join(d, P.REF_NAME if is_key else key + ".png")
        with open(dest, "wb") as f:
            f.write(content)
        return dest

    def _wait_all(self, jobs, t0):
        pending = {prompt_id: (key, prompt_id) for key, prompt_id, _s in jobs}
        results = []
        last_emit = 0.0
        while pending:
            if self._stop.is_set():
                raise Canceled()
            time.sleep(2.0)
            for key, prompt_id in list(pending.values()):
                try:
                    entry = self.comfy.history(prompt_id)
                except ComfyError:
                    continue
                if entry is None:
                    continue
                st = entry.get("status") or {}
                ok = st.get("status_str") == "success"
                images = []
                for _nid, out in (entry.get("outputs") or {}).items():
                    for im in out.get("images") or []:
                        images.append(im)
                item = {"id": key, "ok": bool(ok and images),
                        "elapsed": round(time.time() - t0, 1)}
                if item["ok"]:
                    try:
                        self._save(images, key)
                    except ComfyError as e:
                        item["ok"] = False
                        item["msg"] = str(e)
                else:
                    msgs = [str(m)[:160] for m in (st.get("messages") or [])[:2]]
                    item["msg"] = "出图失败 " + " | ".join(msgs)
                results.append(item)
                self._emit({"type": "page_done", "item": item,
                            "left": len(pending) - 1})
                del pending[prompt_id]

            now = time.time()
            if now - last_emit > 3:
                last_emit = now
                running = pend = 0
                try:
                    q = self.comfy.queue()
                    running = len(q.get("queue_running") or [])
                    pend = len(q.get("queue_pending") or [])
                except ComfyError:
                    pass
                self._emit({"type": "tick", "elapsed": round(now - t0, 1),
                            "running": running, "pending": pend,
                            "left": len(pending)})
        return results
