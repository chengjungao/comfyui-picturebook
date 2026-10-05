"""构造提交给 ComfyUI 的 API 格式工作流。

两个容易踩的坑，都在这里处理掉了：

1. **顶层只能放节点。** 加任何 `_comment` / `meta` 之类的键，ComfyUI 校验时会崩，
   只回一个没有详情的 500。所以注释写在这里，不写进 JSON。
2. **图生图的采样起点取自「文本编码节点」的第 3 个输出**，不是 EmptyLatentImage。
   这不是随手接的：Qwen-Image 的参考图走的是「并排的上下文」通道，
   输出尺寸也跟着第一张参考图走。所以想让全书是横版，主视觉就必须是横版。

参数一律来自配置，读者改 config.json 或界面里的表单即可，不用碰代码。
"""


def _loaders(models, gen):
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": models["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": models["clip"], "type": "qwen_image",
                         "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": models["vae"]}},
        "4": {"class_type": "QwenImage21Cache",
              "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
    }


def _tail(gen, seed, prefix, latent_from):
    return {
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["4", 0], "seed": int(seed),
                         "steps": int(gen["steps"]), "cfg": float(gen["cfg"]),
                         "sampler_name": gen["sampler"], "scheduler": gen["scheduler"],
                         "positive": ["5", 0], "negative": ["5", 1],
                         "latent_image": latent_from, "denoise": 1.0}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def build_t2i(models, gen, prompt, seed, prefix, width=None, height=None,
              negative=""):
    """文生图：用来出角色定妆照（全书一致性的锚点）。"""
    w = int(width or gen["width"])
    h = int(height or gen["height"])
    wf = _loaders(models, gen)
    wf["5"] = {"class_type": "TextEncodeQwenImage21",
               "inputs": {"clip": ["2", 0], "prompt": prompt, "negative_prompt": negative,
                          "vae": ["3", 0], "resolution": int(gen["resolution"])}}
    wf["6"] = {"class_type": "EmptyLatentImage",
               "inputs": {"width": w, "height": h, "batch_size": 1}}
    wf.update(_tail(gen, seed, prefix, ["6", 0]))
    return wf


def build_i2i(models, gen, prompt, seed, prefix, ref_name, negative=""):
    """图生图：把定妆照当参考图，逐页出内页插图。

    ⚠️ 只挂 `images.image_1` 一张参考图，**不要**顺手把上一页的产物也挂进去。
    误差会逐页累积，几页之后主角就认不出来了。
    `image_2` 起的槽位留给配角设定图，不留给上一页。
    """
    wf = _loaders(models, gen)
    wf["10"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
    wf["5"] = {"class_type": "TextEncodeQwenImage21",
               "inputs": {"clip": ["2", 0], "prompt": prompt, "negative_prompt": negative,
                          "vae": ["3", 0], "resolution": int(gen["resolution"]),
                          "images.image_1": ["10", 0]}}
    wf["6"] = {"class_type": "EmptyLatentImage",
               "inputs": {"width": int(gen["width"]), "height": int(gen["height"]),
                          "batch_size": 1}}
    wf.update(_tail(gen, seed, prefix, ["5", 2]))
    return wf


def compose_prompt(prefix, scene, suffix):
    """把「一致性前缀 + 本页画面描述 + 风格后缀」拼成完整提示词。"""
    parts = []
    if prefix.strip():
        parts.append(prefix.strip())
    parts.append(scene.strip())
    if suffix.strip():
        parts.append(suffix.strip())
    return "\n\n".join(parts)


KEY_PROMPT_FIELDS = ("subject", "action", "scene", "style")


def default_key_prompt():
    """没写定妆照提示词时用的默认值 —— 一只干净的全身小狐狸，别自带复杂场景。"""
    return ("儿童绘本主视觉：一只圆眼睛的橘红色小狐狸，全身站立、略侧身看向前方，"
            "白色胸腹，深色爪子，白色尖尖的大尾巴，背上背着一个小布包袱；"
            "它站在秋天的森林里，脚边是金黄色的落叶和红枫叶，温暖的午后阳光穿过树林，"
            "背景柔和虚化。柔和水彩绘本插画风格，温暖秋色，柔和光线，构图干净，"
            "画面内没有任何文字。")
