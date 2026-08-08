"""文件夹扫描、图片识别与缩略图工具。"""

import os

from PIL import Image

from .constants import SUPPORTED_IMAGE_EXTS, THUMB_SIZE


def scan_folder(folder):
    """递归扫描文件夹, 返回 (全部文件路径列表, 排序后的扩展名列表)。"""
    files = []
    exts = set()
    for root, dirs, filenames in os.walk(folder):
        for name in filenames:
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            files.append(path)
            if ext:
                exts.add(ext)
    return files, sorted(exts)


def is_image_file(path):
    """根据扩展名判断是否为支持的图片文件。"""
    return os.path.splitext(path)[1].lower() in SUPPORTED_IMAGE_EXTS


def make_thumbnail(path, size=THUMB_SIZE):
    """生成缩略图; 读取失败时返回 None。"""
    try:
        img = Image.open(path)
        img.thumbnail(size)
        return img
    except Exception:
        return None


def make_placeholder(size=THUMB_SIZE, color=(54, 57, 63)):
    """生成用于占位的纯色缩略图。"""
    return Image.new("RGB", size, color)
