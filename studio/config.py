"""配置读写。

配置放在项目根目录的 config.json，首次运行自动生成默认值。
所有可调项都集中在这里，改配置不用碰代码。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULT = {
    "comfy_url": "http://127.0.0.1:8188",
    "models": {
        "unet": "qwen_image_2.1_int8_convrot.safetensors",
        "clip": "qwen3vl_8b_int8_convrot.safetensors",
        "vae": "qwen_image_2.1_vae_bf16.safetensors",
    },
    "generate": {
        "steps": 25,
        "cfg": 1.0,
        "sampler": "euler",
        "scheduler": "simple",
        "width": 1344,
        "height": 768,
        "resolution": 1024,
        "base_seed": 20261002,
    },
    "book": {
        "page_w_mm": 240,
        "page_h_mm": 180,
        "body_pt": 16,
        "title_pt": 30,
        "paper": "#FDF6E8",
        "ink": "#4A3620",
        "text_font": "KaiTi,楷体,STKaiti,serif",
        "title_font": "FZCuHeiSongS-B-GB,方正粗黑宋简体,Microsoft YaHei,微软雅黑,sans-serif",
    },
    "browser_path": "",
}


def _merge(base, override):
    """按 key 递归合并，保证新增的默认项在旧配置里也能补上。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    if not os.path.exists(CONFIG_PATH):
        save(DEFAULT)
        return dict(DEFAULT)
    try:
        import json
        with io.open(CONFIG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return dict(DEFAULT)
    return _merge(DEFAULT, raw)


def save(cfg):
    import json
    with io.open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(cfg, ensure_ascii=False, indent=2))
    return CONFIG_PATH


def save_and_reload(cfg):
    """保存前先补齐默认项，避免界面漏传字段导致配置残缺。"""
    merged = _merge(DEFAULT, cfg)
    save(merged)
    return merged


def read_json(path, default=None):
    import json
    if not os.path.exists(path):
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    """带父目录创建与中文保留的 JSON 落盘。"""
    import json
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
