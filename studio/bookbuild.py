"""把插图与正文排成一本横版绘本，产出 book.html（再由浏览器转 PDF）。

版式的关键决策：**插图整幅不裁 + 独立文字带**。

插图通常是 16:9 左右（1.75），书页是 4:3（1.333）。如果硬把插图铺满整页再裁切，
会横向切掉约 24%，实测第一版直接把主角的尾巴切没了。
改成「插图按原比例放在上部，下部留一条奶油色文字带」，既不裁切，也顺手把
正文从图里分出来 —— 因为是另外排的，所以不依赖模型会不会写字。
"""
import io
import os

from . import project as P


# ---------- 读图片尺寸（只用标准库，不装 Pillow） ----------

def image_size(path):
    """返回 (宽, 高)，读不出来返回 None。支持 PNG 与 JPEG。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return (int.from_bytes(head[16:20], "big"),
                        int.from_bytes(head[20:24], "big"))
            if head[:2] != b"\xff\xd8":
                return None
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return None
                marker = b[0]
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    continue
                ln = int.from_bytes(f.read(2), "big")
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    data = f.read(5)
                    h = int.from_bytes(data[1:3], "big")
                    w = int.from_bytes(data[3:5], "big")
                    return (w, h)
                f.seek(ln - 2, 1)
    except Exception:
        return None


def _esc(s):
    return (str(s or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


# 版权页里可以用的占位符。书名 / 页数这类东西是算出来的，让人手填迟早写错。
_CO_KEYS = ("书名", "作者", "页数", "尺寸", "开本")


def _fill_colophon(lines, ctx):
    """把版权页里的 {页数} 这类占位符换成真实值。

    读者的版权页多半是照着示例抄的。不替换的话，那句「全书 14 幅插图」
    会原样出现在一本只有 12 页的书上 —— 这是事实错误，不是排版问题，
    所以留一组占位符让它自己算。
    """
    out = []
    for line in lines:
        s = str(line)
        for k in _CO_KEYS:
            s = s.replace("{%s}" % k, str(ctx.get(k, "")))
        out.append(s)
    return out


def build(folder, cfg):
    """按工程文件生成 book.html，返回 (html路径, 统计信息)。"""
    data = P.load(folder)
    if not data:
        raise ValueError("工程文件不存在：" + P.project_path(folder))
    bk = cfg["book"]

    pw, ph = float(bk["page_w_mm"]), float(bk["page_h_mm"])

    # 用第一张真正存在的插图决定插图区高度，保证整幅放得下、不裁切
    ratio = 768.0 / 1344.0
    art_size = (1344, 768)
    for p in data["pages"]:
        ip = P.find_image(folder, p["id"])
        if ip:
            sz = image_size(ip)
            if sz and sz[0]:
                ratio = float(sz[1]) / float(sz[0])
                art_size = sz
                break
    art_h = round(pw * ratio, 3)
    if art_h > ph * 0.92:                 # 图太高，改成按高度排，留一点文字带
        art_h = round(ph * 0.76, 3)
    band_h = round(ph - art_h, 3)

    css = _css(pw, ph, art_h, band_h, bk)
    parts = []
    pidx = 0
    for p in data["pages"]:
        pid, kind = p["id"], p.get("kind") or "page"
        url = P.image_url(folder, pid)
        if not url:
            continue                       # 还没出图的页先跳过，不生成空页
        if kind == "cover":
            parts.append(
                '<section class="page cover">'
                '<div class="artwrap"><img class="art" src="%s" alt="">'
                '<div class="fade"></div></div>'
                '<div class="coverpanel"><h1>%s</h1><div class="rule"></div>'
                "<p>%s</p></div></section>"
                % (url, _esc(p.get("title")), _esc(p.get("subtitle"))))
        elif kind == "back":
            txt = "<br>".join(_esc(t) for t in (p.get("text") or []))
            parts.append(
                '<section class="page cover">'
                '<div class="artwrap"><img class="art" src="%s" alt="">'
                '<div class="fade"></div></div>'
                '<div class="backpanel"><p>%s</p></div></section>' % (url, txt))
        else:
            pidx += 1
            txt = "<br>".join(_esc(t) for t in (p.get("text") or []))
            parts.append(
                '<section class="page">'
                '<div class="artwrap"><img class="art" src="%s" alt="">'
                '<div class="fade"></div></div>'
                '<div class="band"><div class="txt">%s</div>'
                '<div class="pno">%d</div></div></section>'
                % (url, txt, pidx))

    co_ctx = {"书名": data.get("title") or "",
              "作者": data.get("byline") or "",
              "页数": len(parts),
              "尺寸": "%d × %d" % art_size,
              "开本": "%g × %g mm" % (pw, ph)}
    co = "<br>".join(_esc(t) for t in
                     _fill_colophon(data.get("colophon") or [], co_ctx))
    parts.append(
        '<section class="page colophon"><div class="mark">&#10022;</div>'
        "<h2>%s</h2><div class=\"lines\">%s</div>"
        '<div class="byline">%s</div></section>'
        % (_esc(data.get("title")), co, _esc(data.get("byline"))))

    html = (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
        % (_esc(data.get("title")), css, "\n".join(parts)))

    out = os.path.join(folder, "book.html")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return out, {"pages": len(parts), "inner": pidx,
                 "art_h": art_h, "band_h": band_h,
                 "size": "%gx%gmm" % (pw, ph)}


def _rgba0(hexcolor):
    """把 #RRGGBB 变成同色的全透明，用于插图底部的渐隐。"""
    h = str(hexcolor or "").lstrip("#")
    if len(h) != 6:
        return "rgba(255,255,255,0)"
    try:
        return "rgba(%d,%d,%d,0)" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return "rgba(255,255,255,0)"


def _css(pw, ph, art_h, band_h, bk):
    paper = bk["paper"]
    return """@page { size: %(pw)gmm %(ph)gmm; margin: 0; }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { background:#fff; }
body { -webkit-print-color-adjust:exact; print-color-adjust:exact; }

.page { position:relative; overflow:hidden;
  width:%(pw)gmm; height:%(ph)gmm; background:%(paper)s;
  page-break-after:always; break-after:page; }
.page:last-child { page-break-after:auto; break-after:auto; }

.artwrap { position:relative; width:%(pw)gmm; height:%(ah)gmm; overflow:hidden; }
.art { display:block; width:100%%; height:100%%; object-fit:cover; object-position:center; }
.fade { position:absolute; left:0; right:0; bottom:0; height:16mm;
  background:linear-gradient(to bottom, %(paper0)s 0%%, %(paper)s 100%%); }

.band { position:relative; height:%(bh)gmm; padding:7mm 20mm 6mm 20mm; background:%(paper)s; }
.txt { font-family:%(tfont)s; font-size:%(bpt)gpt; line-height:1.66;
  color:%(ink)s; letter-spacing:0.6pt; }
.pno { position:absolute; right:11mm; bottom:4.5mm;
  font-family:Georgia,"Times New Roman",serif; font-size:9pt;
  color:#C4B49A; letter-spacing:1pt; }

.coverpanel { position:relative; height:%(bh)gmm; padding:5mm 20mm 5mm 20mm;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  text-align:center; background:%(paper)s; }
.coverpanel h1 { font-family:%(hfont)s; font-size:%(tpt)gpt; font-weight:400;
  color:#8A4B22; letter-spacing:6pt; text-indent:6pt; line-height:1.2; }
.coverpanel .rule { margin:2.6mm 0 2.2mm 0; width:34mm; height:0;
  border-top:0.5mm solid #DDBE92; }
.coverpanel p { font-family:%(tfont)s; font-size:12.5pt; color:#9A7B52;
  letter-spacing:2.6pt; text-indent:2.6pt; }

.backpanel { position:relative; height:%(bh)gmm; padding:6mm 24mm; box-sizing:border-box;
  display:flex; align-items:center; justify-content:center; text-align:center;
  background:%(paper)s; }
.backpanel p { font-family:%(tfont)s; font-size:15pt; line-height:1.9;
  color:#5C452C; letter-spacing:1.2pt; }

.colophon { display:flex; flex-direction:column; align-items:center;
  justify-content:center; background:%(paper)s; text-align:center; }
.colophon .mark { font-size:26pt; color:#D8A05A; margin-bottom:14mm; }
.colophon h2 { font-family:%(hfont)s; font-size:20pt; color:#8A4B22;
  letter-spacing:4pt; margin-bottom:10mm; }
.colophon .lines { font-family:%(tfont)s; font-size:12pt; line-height:2.1;
  color:#8C7355; letter-spacing:1pt; }
.colophon .byline { margin-top:16mm; font-family:%(tfont)s; font-size:13pt;
  color:#A8865C; letter-spacing:3pt; text-indent:3pt; }
""" % {"pw": pw, "ph": ph, "ah": art_h, "bh": band_h, "paper": paper,
       "paper0": _rgba0(paper),
       "tfont": bk["text_font"], "hfont": bk["title_font"],
       "bpt": bk["body_pt"], "tpt": bk["title_pt"], "ink": bk["ink"]}
