"""绘本工坊 —— 用本地 ComfyUI 把一本绘本从故事做到 PDF。

模块分工：
    config      配置读写（config.json）
    comfy       ComfyUI 客户端（提交、轮询、取图、上传参考图）
    workflows   构造 API 工作流（文生图出定妆照 / 图生图出内页）
    pipeline    出图编排（定妆照 → 批量内页 → 单页重出）
    project     工程文件 project.json 的读写与校验
    bookbuild   排版，产出 book.html
    pdf         调无头浏览器把 HTML 转成 PDF
    web         本地服务与界面
"""

__version__ = "1.0.0"
