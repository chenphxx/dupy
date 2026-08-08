"""主窗口: 文件夹浏览、缩略图预览与重复查找入口。"""

import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import ImageTk

from ..constants import APP_TITLE
from ..dedupe import dedupe_worker
from ..scanner import is_image_file, make_placeholder, make_thumbnail, scan_folder
from ..theme import ThemeManager
from .duplicate_window import DuplicateGroupWindow


class ImageDuplicateFinderApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1200x700")
        root.minsize(900, 520)

        self.theme = ThemeManager(root, "dark")

        self.current_folder = ""
        self.all_files = []
        self.filtered_files = []
        self.extensions = []
        self.thumb_cache = {}
        self.thumb_pil_cache = {}
        self.thumb_box = (180, 180)
        self.thumb_queue = queue.Queue()
        self.thumb_loading = False
        self._preview_h = 200
        self._restoring_preview = False
        self._thumb_resize_job = None
        self.dedupe_thread = None
        self.dedupe_stop_event = None
        self.progress_queue = queue.Queue()
        self.thumb_visible = False
        self.duplicates = []

        self._build_toolbar()
        self._build_stats()
        self._build_main_area()
        self._build_statusbar()

        root.bind_all("<Control-t>", lambda e: self.on_toggle_theme())
        root.after(200, self._poll_progress_queue)

    # -------------------------- 界面构建 --------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, style="Panel.TFrame", padding=(10, 8))
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text="重复图片查找器",
                  style="PanelHeader.TLabel").pack(side="left", padx=(0, 18))

        ttk.Button(bar, text="选择文件夹", style="Secondary.TButton",
                   command=self.on_select_folder).pack(side="left", padx=(0, 6))
        self.lbl_folder = ttk.Label(bar, text="当前文件夹: (未选择)",
                                    style="PanelMuted.TLabel", width=44, anchor="w")
        self.lbl_folder.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="刷新扫描", style="Secondary.TButton",
                   command=self._rescan_current_folder).pack(side="left", padx=(0, 8))

        ttk.Label(bar, text="筛选类型:", style="Panel.TLabel").pack(side="left", padx=(6, 2))
        self.combo_ext = ttk.Combobox(bar, state="readonly", width=10)
        self.combo_ext.pack(side="left")
        self.combo_ext.bind("<<ComboboxSelected>>",
                            lambda e: self.apply_filter_and_show_list())

        ttk.Button(bar, text="显示缩略图", style="Secondary.TButton",
                   command=self.on_show_thumbnails).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="查找重复项", style="Accent.TButton",
                   command=self.on_find_duplicates).pack(side="left", padx=(8, 0))

        self.btn_theme = ttk.Button(bar, text="☾ 深色模式",
                                    style="Secondary.TButton",
                                    command=self.on_toggle_theme)
        self.btn_theme.pack(side="right")

    def _build_stats(self):
        stats = ttk.Frame(self.root, padding=(12, 4))
        stats.pack(side="top", fill="x")
        self.lbl_total = ttk.Label(stats, text="总文件数: 0", style="Muted.TLabel")
        self.lbl_total.pack(side="left", padx=(0, 14))
        self.lbl_filtered = ttk.Label(stats, text="筛选后文件数: 0",
                                      style="Muted.TLabel")
        self.lbl_filtered.pack(side="left")

    def _build_main_area(self):
        main = ttk.Frame(self.root)
        main.pack(side="top", fill="both", expand=True)

        # 可拖拽分隔的垂直分栏: 上方文件列表, 下方缩略图预览
        self.paned = ttk.Panedwindow(main, orient="vertical")
        self.paned.pack(side="top", fill="both", expand=True)

        list_frame = ttk.Frame(self.paned, padding=(12, 8))
        self.paned.add(list_frame, weight=1)
        self.tree = ttk.Treeview(list_frame, columns=("name", "ext", "path"),
                                 show="headings")
        self.tree.heading("name", text="文件名")
        self.tree.heading("ext", text="后缀")
        self.tree.heading("path", text="路径")
        self.tree.column("name", width=400, anchor="w")
        self.tree.column("ext", width=80, anchor="center")
        self.tree.column("path", width=600, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                         command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree_scroll.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Button-3>", self.on_tree_right_click)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="打开文件", command=self.open_selected_file)
        self.menu.add_command(label="打开所在文件夹",
                              command=self.open_file_location)

        # 缩略图展示区 (默认隐藏)
        self.thumb_canvas_container = ttk.Frame(self.paned)
        self.thumb_canvas = tk.Canvas(self.thumb_canvas_container, height=200,
                                      bg=self.theme.palette["bg"],
                                      highlightthickness=0)
        self.thumb_canvas.pack(side="left", fill="both", expand=True)
        self.thumb_scroll = ttk.Scrollbar(self.thumb_canvas_container,
                                          orient="horizontal",
                                          command=self.thumb_canvas.xview)
        self.thumb_scroll.pack(side="bottom", fill="x")
        self.thumb_canvas.configure(xscrollcommand=self.thumb_scroll.set)
        self.thumb_frame = ttk.Frame(self.thumb_canvas)
        self.thumb_canvas.create_window((0, 0), window=self.thumb_frame,
                                        anchor="nw")
        self.thumb_frame.bind(
            "<Configure>",
            lambda e: self.thumb_canvas.configure(
                scrollregion=self.thumb_canvas.bbox("all")))
        self.thumb_canvas.bind("<Enter>", self._bind_thumb_mousewheel)
        self.thumb_canvas.bind("<Leave>", self._unbind_thumb_mousewheel)
        self.thumb_frame.bind("<Enter>", self._bind_thumb_mousewheel)
        self.thumb_frame.bind("<Leave>", self._unbind_thumb_mousewheel)
        self.paned.add(self.thumb_canvas_container, weight=0)
        self.paned.forget(self.thumb_canvas_container)  # 默认隐藏
        self.thumb_canvas_container.bind("<Configure>",
                                         self._on_thumb_pane_configure)

    def _build_statusbar(self):
        status = ttk.Frame(self.root, style="Panel.TFrame", padding=(10, 6))
        status.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(status, orient="horizontal",
                                        mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.lbl_progress_text = ttk.Label(status, text="进度: 0% (0/0)",
                                           style="Panel.TLabel")
        self.lbl_progress_text.pack(side="left", padx=(0, 8))
        self.btn_stop = ttk.Button(status, text="终止", style="Danger.TButton",
                                   command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left")

    # -------------------------- 主题切换 --------------------------
    def on_toggle_theme(self):
        self.theme.toggle()
        self.btn_theme.config(text="☾ 深色模式" if self.theme.is_dark
                              else "☀ 浅色模式")

    # -------------------------- 文件打开 --------------------------
    def _open_file(self, path):
        try:
            os.startfile(path)
        except AttributeError:
            try:
                subprocess.Popen(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开文件: {e}")

    def _open_file_location(self, path):
        folder = os.path.dirname(path)
        try:
            subprocess.Popen(f'explorer /select,"{path}"')
        except Exception:
            try:
                subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                messagebox.showerror("错误", f"无法打开文件夹: {e}")

    # -------------------------- Tree 操作 --------------------------
    def on_tree_double_click(self, event):
        self.open_selected_file()

    def on_tree_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.menu.post(event.x_root, event.y_root)

    def open_selected_file(self):
        selection = self.tree.selection()
        if selection:
            path = self.tree.item(selection[0])["values"][2]
            self._open_file(path)

    def open_file_location(self):
        selection = self.tree.selection()
        if selection:
            path = self.tree.item(selection[0])["values"][2]
            self._open_file_location(path)

    # -------------------------- 文件夹选择 / 扫描 --------------------------
    def on_select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.current_folder = folder
            self.lbl_folder.config(text=f"当前文件夹: {folder}")
            self._scan_folder(folder)

    def _rescan_current_folder(self):
        if self.current_folder:
            self._scan_folder(self.current_folder)

    def _scan_folder(self, folder):
        self.all_files, exts = scan_folder(folder)
        self.extensions = exts
        self.combo_ext["values"] = ["全部"] + exts
        self.combo_ext.current(0)
        self.apply_filter_and_show_list()

    # -------------------------- 筛选 / 列表显示 --------------------------
    def apply_filter_and_show_list(self):
        selected_ext = self.combo_ext.get()
        if selected_ext == "全部":
            self.filtered_files = [f for f in self.all_files if is_image_file(f)]
        else:
            self.filtered_files = [f for f in self.all_files
                                   if f.lower().endswith(selected_ext)]
        self.tree.delete(*self.tree.get_children())
        for f in self.filtered_files:
            self.tree.insert("", "end", values=(
                os.path.basename(f), os.path.splitext(f)[1].lower(), f))
        self.lbl_total.config(text=f"总文件数: {len(self.all_files)}")
        self.lbl_filtered.config(
            text=f"筛选后文件数: {len(self.filtered_files)}")

    # -------------------------- 缩略图 --------------------------
    def on_show_thumbnails(self):
        if self.thumb_visible:
            self.paned.forget(self.thumb_canvas_container)
            self.thumb_visible = False
            self.thumb_loading = False
            self._restoring_preview = False
        else:
            self.thumb_box = self._current_thumb_box()
            self._restoring_preview = True
            self.paned.add(self.thumb_canvas_container, weight=0)
            self.root.after_idle(self._apply_preview_height)
            self.thumb_visible = True
            self.thumb_loading = True
            self.thumb_queue = queue.Queue()
            for widget in self.thumb_frame.winfo_children():
                widget.destroy()
            self.progress["maximum"] = len(self.filtered_files)
            self.progress["value"] = 0
            threading.Thread(target=self._load_thumbnails_thread,
                             daemon=True).start()
            self.root.after(60, self._poll_thumb_queue)

    def _load_thumbnails_thread(self):
        """后台线程: 只做 PIL 缩略图计算, 结果经队列交给主线程渲染。"""
        for f in self.filtered_files:
            if f not in self.thumb_pil_cache:
                img = make_thumbnail(f, size=(512, 512))
                if img is None:
                    img = make_placeholder(
                        color=self.theme.palette["placeholder"])
                self.thumb_pil_cache[f] = img
            self.thumb_queue.put(f)
        self.thumb_queue.put(None)

    def _poll_thumb_queue(self):
        """主线程轮询缩略图队列并渲染。"""
        processed = 0
        while processed < 25:
            try:
                item = self.thumb_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if item is None:
                self.thumb_loading = False
                self.progress["value"] = 0
                self.lbl_progress_text.config(text="缩略图加载完成")
                self._rerender_thumbnails()
                return
            f = item
            img = self.thumb_pil_cache.get(f)
            if img is not None:
                tkimg = self._make_thumb_photo(img, f)
                self.thumb_cache[f] = tkimg
                lbl = tk.Label(self.thumb_frame, image=tkimg,
                               bg=self.theme.palette["bg"])
                lbl.image = tkimg
                lbl.path = f
                lbl.pack(side="left", padx=4, pady=4)
                lbl.bind("<Double-1>", lambda e, p=f: self._open_file(p))
                lbl.bind("<Button-3>",
                         lambda e, p=f: self._open_file_location(p))
            self.progress["value"] += 1
            self.lbl_progress_text.config(
                text=f"加载缩略图: {self.progress['value']}/"
                     f"{len(self.filtered_files)}")
        if self.thumb_visible and self.thumb_loading:
            self.root.after(60, self._poll_thumb_queue)

    def _bind_thumb_mousewheel(self, event=None):
        self.thumb_canvas.bind_all("<MouseWheel>", self._on_thumb_mousewheel)

    def _unbind_thumb_mousewheel(self, event=None):
        self.thumb_canvas.unbind_all("<MouseWheel>")

    def _on_thumb_mousewheel(self, event):
        self.thumb_canvas.xview_scroll(-1 * (event.delta // 120), "units")

    # -------------------------- 预览区拖拽调整高度 --------------------------
    def _on_thumb_pane_configure(self, event):
        if self._restoring_preview:
            return
        if event.height >= 10:
            self._preview_h = event.height
            self._schedule_thumb_rerender()

    def _apply_preview_height(self, retries=40):
        """把预览区高度调整到上次拖拽后的数值, 未生效则重试直至稳定。"""
        try:
            total = self.paned.winfo_height()
            desired = max(40, min(self._preview_h, total - 40))
            if total > desired + 20:
                self.paned.sashpos(0, total - desired)
            # 窗格未映射时 winfo_height 返回的是请求高度, 不可作准
            mapped = self.thumb_canvas_container.winfo_ismapped()
            current = self.thumb_canvas_container.winfo_height()
            if mapped and abs(current - desired) <= 8:
                self._restoring_preview = False
                self._schedule_thumb_rerender()
                return
            if mapped and abs(current - desired) > 30:
                # 用户已手动拖动分隔条, 停止恢复并采用当前高度
                self._restoring_preview = False
                self._preview_h = current
                self._schedule_thumb_rerender()
                return
            if retries > 0:
                self.root.after(
                    100, lambda: self._apply_preview_height(retries - 1))
            else:
                self._restoring_preview = False
        except tk.TclError:
            self._restoring_preview = False

    def _current_thumb_box(self):
        h = self._preview_h or 200
        side = max(48, min(720, h - 16))
        return (side, side)

    def _make_thumb_photo(self, img, path=None):
        # 目标尺寸超过缓存源图时, 从磁盘重新读取更大的版本
        if path is not None and max(self.thumb_box) > max(img.size):
            big = make_thumbnail(path, size=self.thumb_box)
            if big is not None:
                img = big
        fit = img.copy()
        fit.thumbnail(self.thumb_box)
        return ImageTk.PhotoImage(fit)

    def _schedule_thumb_rerender(self):
        if self._thumb_resize_job is not None:
            try:
                self.root.after_cancel(self._thumb_resize_job)
            except Exception:
                pass
        self._thumb_resize_job = self.root.after(80, self._rerender_thumbnails)

    def _rerender_thumbnails(self):
        self._thumb_resize_job = None
        if not self.thumb_visible or self.thumb_loading:
            return
        self.thumb_box = self._current_thumb_box()
        for child in self.thumb_frame.winfo_children():
            child.destroy()
        for f in self.filtered_files:
            img = self.thumb_pil_cache.get(f)
            if img is None:
                img = make_thumbnail(f)
                if img is None:
                    img = make_placeholder(
                        color=self.theme.palette["placeholder"])
                self.thumb_pil_cache[f] = img
            tkimg = self._make_thumb_photo(img, f)
            self.thumb_cache[f] = tkimg
            lbl = tk.Label(self.thumb_frame, image=tkimg,
                           bg=self.theme.palette["bg"])
            lbl.image = tkimg
            lbl.path = f
            lbl.pack(side="left", padx=4, pady=4)
            lbl.bind("<Double-1>", lambda e, p=f: self._open_file(p))
            lbl.bind("<Button-3>",
                     lambda e, p=f: self._open_file_location(p))

    # -------------------------- 重复查找 --------------------------
    def on_find_duplicates(self):
        if not self.filtered_files:
            messagebox.showinfo("提示", "没有可处理文件")
            return
        if self.dedupe_thread and self.dedupe_thread.is_alive():
            messagebox.showwarning("警告", "正在进行重复查找")
            return
        self.dedupe_stop_event = threading.Event()
        self.dedupe_thread = threading.Thread(
            target=dedupe_worker,
            args=(self.filtered_files, self.progress_queue,
                  self.dedupe_stop_event),
            daemon=True)
        self.dedupe_thread.start()
        self.btn_stop.config(state="normal")

    def on_stop(self):
        if self.dedupe_stop_event:
            self.dedupe_stop_event.set()

    def _poll_progress_queue(self):
        try:
            while True:
                item = self.progress_queue.get_nowait()
                if item[0] == "progress":
                    processed, total = item[1], item[2]
                    self.progress["maximum"] = total
                    self.progress["value"] = processed
                    self.lbl_progress_text.config(
                        text=f"重复查找: {processed}/{total}")
                elif item[0] == "result":
                    self.duplicates = item[1]
                elif item[0] == "done":
                    self.btn_stop.config(state="disabled")
                    self.progress["value"] = 0
                    self.lbl_progress_text.config(text="重复查找完成")
                    if self.duplicates:
                        DuplicateGroupWindow(self.root, self.duplicates,
                                             self.all_files, theme=self.theme)
                    else:
                        messagebox.showinfo("提示", "未发现重复图片")
                elif item[0] == "stopped":
                    self.btn_stop.config(state="disabled")
                    self.progress["value"] = 0
                    self.lbl_progress_text.config(text="重复查找被终止")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_progress_queue)
