"""重复图片检测工作线程。"""

import imagehash
from PIL import Image

from .constants import HASH_THRESHOLD


def dedupe_worker(file_list, progress_queue, stop_event,
                  hash_func=imagehash.dhash, threshold=HASH_THRESHOLD):
    """在后台线程中计算感知哈希并按相似度分组。

    通过 progress_queue 发送消息:
      ("progress", processed, total) - 进度
      ("result", groups)             - 重复分组结果
      ("done",)                      - 正常完成
      ("stopped",)                   - 被终止
    """
    total = len(file_list)
    processed = 0
    hashes = []
    for path in file_list:
        if stop_event.is_set():
            progress_queue.put(("stopped",))
            return
        try:
            with Image.open(path) as im:
                h = hash_func(im)
        except Exception:
            h = None
        hashes.append((h, path))
        processed += 1
        progress_queue.put(("progress", processed, total))

    groups = []
    used = [False] * len(hashes)
    for i, (hi, pi) in enumerate(hashes):
        if stop_event.is_set():
            progress_queue.put(("stopped",))
            return
        if used[i] or hi is None:
            continue
        group = [pi]
        used[i] = True
        for j in range(i + 1, len(hashes)):
            hj, pj = hashes[j]
            if used[j] or hj is None:
                continue
            try:
                if abs(hi - hj) <= threshold:
                    group.append(pj)
                    used[j] = True
            except Exception:
                pass
        if len(group) > 1:
            groups.append(group)
    progress_queue.put(("result", groups))
    progress_queue.put(("done",))
