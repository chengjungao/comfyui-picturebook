"""绘本工程文件（project.json）的读写与校验。

一个工程就是一个文件夹：

    我的绘本/
      project.json    分镜、正文、风格，全在这一个文件里
      img/            出好的图（含 char_sheet.png 定妆照）
      book.html       排版结果
      我的绘本.pdf     最终成品

原来散在 pages.json + text.json 两个文件里，界面上编辑很别扭；
合并成一个，读者只需理解「有一个工程文件」。
"""
import io
import json
import os
import re

PROJECT_NAME = "project.json"
IMG_DIR = "img"
REF_NAME = "char_sheet.png"

KINDS = ("cover", "page", "back")


def project_path(folder):
    return os.path.join(folder, PROJECT_NAME)


def img_dir(folder):
    return os.path.join(folder, IMG_DIR)


def image_path(folder, pid):
    return os.path.join(img_dir(folder), pid + ".png")


def find_image(folder, pid):
    """返回这一页实际存在的图片路径（优先 png，也认 jpg），没有则 None。

    认 jpg 是为了读者自己换图方便：从别处导出成 jpg 直接丢进 img/ 也能用。
    """
    d = img_dir(folder)
    for ext in (".png", ".jpg", ".jpeg"):
        p = os.path.join(d, pid + ext)
        if os.path.exists(p):
            return p
    return None


def image_url(folder, pid):
    """给 HTML 用的相对路径（相对工程目录）。"""
    p = find_image(folder, pid)
    return (IMG_DIR + "/" + os.path.basename(p)) if p else None


def new(title="我的绘本"):
    return {
        "title": title,
        "byline": "",
        "colophon": [
            "本册插图由本机运行的开放权重模型生成",
            "文字与版式由作者手工编排",
        ],
        "style": {
            "prefix": "保持参考图中这只主角的样貌、配色和画风完全一致。",
            "suffix": "柔和水彩绘本插画风格，温暖色调，柔和光线，构图干净，"
                      "留有余地，画面内没有任何文字。",
            "key_prompt": "",
        },
        "pages": [
            {"id": "00-cover", "kind": "cover", "scene": "",
             "title": title, "subtitle": ""},
            {"id": "01-page", "kind": "page", "scene": "", "text": ["", ""]},
            {"id": "99-back", "kind": "back", "scene": "", "text": ["", ""]},
        ],
    }


def load(folder):
    p = project_path(folder)
    if not os.path.exists(p):
        return None
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def save(folder, data):
    if not os.path.isdir(folder):
        os.makedirs(folder)
    if not os.path.isdir(img_dir(folder)):
        os.makedirs(img_dir(folder))
    with io.open(project_path(folder), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    return project_path(folder)


# ---------- 校验 ----------

def validate(data):
    """返回 [(级别, 说明)]，级别为 error / warn。界面直接展示。"""
    out = []
    if not data:
        return [("error", "工程文件读不出来")]
    title = (data.get("title") or "").strip()
    if not title:
        out.append(("error", "还没填书名"))
    pages = data.get("pages") or []
    if not pages:
        out.append(("error", "一页都没有"))
        return out

    n_page = n_cover = n_back = 0
    seen = set()
    for i, p in enumerate(pages, 1):
        pid = p.get("id") or ""
        kind = p.get("kind") or "page"
        if kind not in KINDS:
            out.append(("error", "第 %d 条的类型不认识：%s" % (i, kind)))
        if not pid:
            out.append(("error", "第 %d 条缺 id" % i))
        elif pid in seen:
            out.append(("error", "id 重复：%s（会互相覆盖图片）" % pid))
        elif not re.match(r"^[A-Za-z0-9_-]+$", pid):
            out.append(("warn", "id 「%s」含特殊字符，建议只用字母数字和连字符" % pid))
        seen.add(pid)

        if not (p.get("scene") or "").strip():
            out.append(("warn", "「%s」还没写画面描述，出图会没有内容" % (pid or i)))
        if kind == "page":
            n_page += 1
            txt = [t for t in (p.get("text") or []) if (t or "").strip()]
            if not txt:
                out.append(("warn", "内页「%s」还没有正文" % pid))
        elif kind == "cover":
            n_cover += 1
            if not (p.get("title") or "").strip():
                out.append(("warn", "封面还没写书名"))
        elif kind == "back":
            n_back += 1

    if n_cover == 0:
        out.append(("warn", "没有封面页"))
    if n_back == 0:
        out.append(("warn", "没有封底页"))
    if n_page == 0:
        out.append(("error", "没有内页"))
    if not (data.get("style", {}).get("suffix") or "").strip():
        out.append(("warn", "还没写风格后缀，全书画风可能不统一"))
    return out


def stats(data):
    pages = (data or {}).get("pages") or []
    d = {"cover": 0, "page": 0, "back": 0, "total": len(pages), "words": 0}
    for p in pages:
        k = p.get("kind") or "page"
        if k in d:
            d[k] += 1
        for t in (p.get("text") or []):
            d["words"] += len(re.sub(r"\s", "", t or ""))
    return d


# ---------- 从旧的两文件格式迁移 ----------

def migrate(folder):
    """把 pages.json + text.json 合并成 project.json（老工程升级用）。"""
    pj = os.path.join(folder, "pages.json")
    tj = os.path.join(folder, "text.json")
    if not os.path.exists(pj):
        return None
    with io.open(pj, encoding="utf-8") as f:
        pg = json.load(f)
    texts, meta = {}, {}
    if os.path.exists(tj):
        with io.open(tj, encoding="utf-8") as f:
            t = json.load(f)
        texts = t.get("text") or {}
        meta = t.get("meta") or {}

    pages = []
    for p in pg.get("pages") or []:
        pid = p.get("id")
        kind = p.get("kind") or "page"
        d = {"id": pid, "kind": kind, "scene": p.get("scene", "")}
        d["title"] = p.get("title", "")
        if kind == "cover":
            td = texts.get(pid) or {}
            if isinstance(td, dict):
                d["title"] = td.get("title", d["title"])
                d["subtitle"] = td.get("subtitle", "")
        else:
            td = texts.get(pid)
            d["text"] = list(td) if isinstance(td, list) else []
        pages.append(d)

    return {
        "title": meta.get("title") or "我的绘本",
        "byline": meta.get("byline") or "",
        "colophon": list(meta.get("colophon") or new()["colophon"]),
        "style": {
            "prefix": pg.get("style_prefix", ""),
            "suffix": pg.get("style_suffix", ""),
            "key_prompt": "",
        },
        "pages": pages,
    }
