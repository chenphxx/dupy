"""重复分组窗口: 逐组勾选保留图片, 支持删除与保存整理。"""

import os
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import ImageTk

from ..constants import DUP_SUBFOLDER_NAME
from ..scanner import make_placeholder, make_thumbnail


def _short_name(path, limit=16):
    """截断文件名, 超出部分用省略号代替。"""
    name = os.path.basename(path)
    return name if len(name) <= limit else name[:limit - 1] + "…"


class DuplicateGroupWindow(tk.Toplevel):
    def __init__(self, master, groups, all_files, theme):
        super().__init__(master)
        self.title("重复图片分组 - 秋白")
        self.geometry("1400x1000")
        self.theme = theme
        self.theme.register(self)

        self.groups = groups
        self.all_files = all_files
        self.thumb_cache = {}
        self.thumb_pil_cache = {}
        self.selected = {}
        self.target_folder = ""
        self.dup_subfolder_name = DUP_SUBFOLDER_NAME
        self._layout_job = None
        self._last_canvas_w = 1000

        self._build_toolbar()
        self._build_canvas()
        self.populate_groups()
        self.theme.apply_theme(self)

    # -------------------------- 界面构建 --------------------------
    def _build_toolbar(self):
        top = ttk.Frame(self, style="Panel.TFrame", padding=(8, 8))
        top.pack(side="top", fill="x")
        ttk.Label(top, text="重复图片分组",
                  style="PanelHeader.TLabel").pack(side="left", padx=(0, 14))

        self.btn_target = ttk.Button(top, text="选择目标文件夹",
                                     style="Secondary.TButton",
                                     command=self.select_target_folder)
        self.btn_target.pack(side="left")
        self.lbl_target = ttk.Label(top, text="未选择",
                                    style="PanelMuted.TLabel", width=40,
                                    anchor="w")
        self.lbl_target.pack(side="left", padx=(8, 0))
        self.btn_save = ttk.Button(top, text="保存选中图片",
                                   style="Accent.TButton",
                                   command=self.save_selected)
        self.btn_save.pack(side="left", padx=(16, 0))

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y",
                                                   padx=14)

        ttk.Button(top, text="取消勾选", style="Secondary.TButton",
                   command=self.deselect_all).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="反选", style="Secondary.TButton",
                   command=self.inverse_select).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="批量勾选第一个", style="Secondary.TButton",
                   command=self.default_select).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="删除已勾选", style="Danger.TButton",
                   command=self.delete_checked).pack(side="left", padx=(0, 6))

    def _build_canvas(self):
        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(self.canvas_frame,
                                bg=self.theme.palette["bg"],
                                highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical",
                                       command=self.canvas.yview)
        self.scrollbar.pack(side="left", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner_frame = ttk.Frame(self.canvas)
        self._inner_window_id = self.canvas.create_window(
            (0, 0), window=self.inner_frame, anchor="nw")
        self.inner_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
        # 窗口尺寸变化 -> 内层宽度跟随 + 防抖重排
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # 鼠标滚轮绑定
        self.inner_frame.bind("<Enter>", self._bind_mousewheel)
        self.inner_frame.bind("<Leave>", self._unbind_mousewheel)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, event=None):
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, event=None):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        bbox = self.canvas.bbox("all")
        if bbox is None:
            return
        canvas_height = self.canvas.winfo_height()
        scrollable_height = bbox[3] - canvas_height
        if scrollable_height <= 0:
            return
        if hasattr(event, "delta"):
            self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
        else:
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

    # -------------------------- 响应式布局 --------------------------
    def _on_canvas_configure(self, event):
        self._last_canvas_w = event.width
        try:
            self.canvas.itemconfigure(self._inner_window_id, width=event.width)
        except tk.TclError:
            pass
        self._schedule_relayout()

    def _schedule_relayout(self):
        if self._layout_job is not None:
            try:
                self.after_cancel(self._layout_job)
            except Exception:
                pass
        self._layout_job = self.after(120, self._relayout)

    def populate_groups(self):
        """重建分组卡片 (重置勾选为每组第一个)。"""
        self._relayout(preserve=False)

    def _relayout(self, preserve=True):
        """根据当前窗口宽度重算列数与图片大小并重建卡片。"""
        self._layout_job = None
        for w in self.inner_frame.winfo_children():
            w.destroy()
        if not self.groups:
            self.theme.apply_theme(self)
            return

        canvas_w = max(400, self._last_canvas_w
                       or self.canvas.winfo_width() or 1000)
        cols = max(1, min(len(self.groups), canvas_w // 380))
        card_w = (canvas_w - (cols + 1) * 16) / cols

        for idx, group in enumerate(self.groups):
            row, col = divmod(idx, cols)
            if not preserve or idx not in self.selected:
                self.selected[idx] = group[0]

            frame = ttk.LabelFrame(self.inner_frame, text=f"组 {idx + 1}",
                                   padding=6)
            frame.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            self.inner_frame.columnconfigure(col, weight=1)
            self.inner_frame.rowconfigure(row, weight=1)

            # 组内图片分几行展示: 每行最多按卡片宽度 170px 一张
            slots_per_row = max(1, min(len(group), max(1, int(card_w // 170))))
            slot_w = card_w / slots_per_row
            thumb_side = max(48, min(240, int(slot_w - 30)))
            for i, pi in enumerate(group):
                r, c = divmod(i, slots_per_row)
                self._add_image_slot(frame, pi, idx, thumb_side, r, c,
                                     slots_per_row)
        self.theme.apply_theme(self)

    def _add_image_slot(self, card, path, group_idx, thumb_side, row, col,
                        slots_per_row):
        slot = ttk.Frame(card)
        slot.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
        card.columnconfigure(col, weight=1)
        card.rowconfigure(row, weight=1)

        img = self.thumb_pil_cache.get(path)
        if img is None:
            img = make_thumbnail(path, size=(512, 512))
            if img is None:
                img = make_placeholder(color=self.theme.palette["placeholder"])
            self.thumb_pil_cache[path] = img
        fit = img.copy()
        fit.thumbnail((thumb_side, thumb_side))
        tkimg = ImageTk.PhotoImage(fit)
        self.thumb_cache[path] = tkimg

        chk_var = tk.IntVar(
            value=1 if self.selected.get(group_idx) == path else 0)
        chk = ttk.Checkbutton(slot, image=tkimg, variable=chk_var,
                              text=_short_name(path), compound="top",
                              style="Card.TCheckbutton")
        chk.pack(side="top", fill="both", expand=True)
        chk.var = chk_var
        chk.path = path
        chk.group_idx = group_idx
        chk.config(command=lambda c=chk: self.on_check(c))
        chk.bind("<Double-1>", lambda e, p=path: self._open_file(p))
        chk.bind("<Button-3>", lambda e, p=path: self._open_file_location(p))

        btn_del = ttk.Button(slot, text="删除", style="Danger.TButton",
                             command=lambda p=path, cb=chk:
                             self.delete_file(p, cb))
        btn_del.pack(side="bottom", fill="x", pady=(2, 0))

    # -------------------------- 分组展示 --------------------------
    def select_target_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.target_folder = folder
            self.lbl_target.config(text=folder)

    # -------------------------- 勾选操作 --------------------------
    def on_check(self, chk):
        idx = chk.group_idx
        if chk.var.get():
            self.selected[idx] = chk.path
        else:
            if self.selected.get(idx) == chk.path:
                self.selected[idx] = None

    def _all_checkbuttons(self):
        """递归收集所有图片勾选框。"""
        for child in self.inner_frame.winfo_children():
            for slot in child.winfo_children():
                for w in slot.winfo_children():
                    if hasattr(w, "var"):
                        yield w

    def deselect_all(self):
        for w in self._all_checkbuttons():
            w.var.set(0)
        self.selected = {}

    def inverse_select(self):
        for w in self._all_checkbuttons():
            idx = w.group_idx
            if w.path in self.groups[idx]:
                w.var.set(0 if w.var.get() else 1)
                if w.var.get():
                    self.selected[idx] = w.path
                elif self.selected.get(idx) == w.path:
                    self.selected[idx] = None

    def default_select(self):
        for idx, group in enumerate(self.groups):
            if not group:
                continue
            self.selected[idx] = group[0]
        self.populate_groups()

    # -------------------------- 删除 --------------------------
    def delete_checked(self):
        to_delete = []
        for idx, group in enumerate(self.groups):
            sel_file = self.selected.get(idx)
            if sel_file:
                to_delete.append((sel_file, idx))
        if not to_delete:
            messagebox.showinfo("提示", "没有已勾选的文件")
            return
        if not messagebox.askyesno(
                "删除确认",
                f"确定要删除 {len(to_delete)} 个已勾选文件吗？"):
            return
        for path, idx in to_delete:
            try:
                os.remove(path)
            except Exception as e:
                messagebox.showerror("错误", f"删除失败: {path}\n{e}")
            for group in self.groups:
                if path in group:
                    group.remove(path)
            self.selected[idx] = None
            if path in self.thumb_cache:
                del self.thumb_cache[path]
            if path in self.thumb_pil_cache:
                del self.thumb_pil_cache[path]
        self.groups = [g for g in self.groups if len(g) > 1]
        self.populate_groups()

    def delete_file(self, path, checkbox):
        if messagebox.askyesno(
                "删除确认",
                f"确定要从磁盘删除 {os.path.basename(path)} 吗？"):
            try:
                os.remove(path)
                if path in self.thumb_cache:
                    del self.thumb_cache[path]
                if path in self.thumb_pil_cache:
                    del self.thumb_pil_cache[path]
                for group in self.groups:
                    if path in group:
                        group.remove(path)
                        break
                self.groups = [g for g in self.groups if len(g) > 1]
                self.populate_groups()
            except Exception as e:
                messagebox.showerror("错误", f"删除失败: {e}")

    # -------------------------- 打开文件 --------------------------
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

    # -------------------------- 保存 --------------------------
    def save_selected(self):
        if not self.target_folder:
            messagebox.showwarning("警告", "请先选择目标文件夹")
            return
        if not os.path.exists(self.target_folder):
            os.makedirs(self.target_folder)
        if os.listdir(self.target_folder):
            if not messagebox.askyesno(
                    "提示", "目标文件夹不为空，是否清空？"):
                return
            for f in os.listdir(self.target_folder):
                fp = os.path.join(self.target_folder, f)
                try:
                    if os.path.isdir(fp):
                        shutil.rmtree(fp)
                    else:
                        os.remove(fp)
                except Exception:
                    pass

        dup_subfolder = os.path.join(self.target_folder,
                                     self.dup_subfolder_name)
        if not os.path.exists(dup_subfolder):
            os.makedirs(dup_subfolder)

        no_dup_files = [f for f in self.all_files
                        if all(f not in g for g in self.groups)]
        for f in no_dup_files:
            shutil.copy2(f, self.target_folder)
        for idx, group in enumerate(self.groups):
            sel_file = self.selected.get(idx)
            for f in group:
                if f == sel_file:
                    shutil.copy2(f, self.target_folder)
                else:
                    shutil.copy2(f, dup_subfolder)
        messagebox.showinfo("完成", "已保存选中图片")
