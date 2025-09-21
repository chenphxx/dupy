import os, shutil, threading, queue, subprocess, hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, UnidentifiedImageError
import imagehash
import pickle

THUMB_SIZE = (150, 150)
HASH_FUNC = imagehash.dhash
HASH_THRESHOLD = 5
SUPPORTED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
CACHE_FOLDER = ".thumb_cache"

def human_count(n):
    return f"{n}"

def scan_folder(folder):
    files = []
    exts = set()
    for root, dirs, filenames in os.walk(folder):
        for f in filenames:
            path = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            files.append(path)
            if ext:
                exts.add(ext)
    return files, sorted(exts)

def is_image_file(path):
    return os.path.splitext(path)[1].lower() in SUPPORTED_IMAGE_EXTS

def make_thumbnail(path, size=THUMB_SIZE):
    try:
        img = Image.open(path)
        img.thumbnail(size)
        return img
    except:
        return None

def dedupe_worker(file_list, progress_queue, stop_event, hash_func=HASH_FUNC, threshold=HASH_THRESHOLD):
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
        except:
            h = None
        hashes.append((h, path))
        processed += 1
        progress_queue.put(("progress", processed, total))
    groups = []
    used = [False]*len(hashes)
    for i, (hi, pi) in enumerate(hashes):
        if stop_event.is_set():
            progress_queue.put(("stopped",))
            return
        if used[i] or hi is None:
            continue
        group = [pi]
        used[i] = True
        for j in range(i+1, len(hashes)):
            hj, pj = hashes[j]
            if used[j] or hj is None:
                continue
            try:
                if abs(hi - hj) <= threshold:
                    group.append(pj)
                    used[j] = True
            except:
                pass
        if len(group) > 1:
            groups.append(group)
    progress_queue.put(("result", groups))
    progress_queue.put(("done",))

class DuplicateGroupWindow(tk.Toplevel):
    def __init__(self, master, groups, all_files):
        super().__init__(master)
        self.title("重复图片分组 - 秋白")
        self.geometry("1400x1000")
        self.groups = groups
        self.all_files = all_files
        self.thumb_cache = {}
        self.selected = {}
        self.target_folder = ""
        self.dup_subfolder_name = "重复项"

        # 顶部目标文件夹 & 保存按钮
        top_frame = ttk.Frame(self, padding=(4,4))
        top_frame.pack(side="top", fill="x")
        self.btn_target = ttk.Button(top_frame, text="选择目标文件夹", command=self.select_target_folder)
        self.btn_target.pack(side="left")
        self.lbl_target = ttk.Label(top_frame, text="未选择")
        self.lbl_target.pack(side="left", padx=(6,0))
        self.btn_save = ttk.Button(top_frame, text="保存选中图片", command=self.save_selected)
        self.btn_save.pack(side="left", padx=(20,0))

        # 反选/全选/取消/默认按钮
        self.btn_frame = ttk.Frame(top_frame)
        self.btn_frame.pack(side="left", padx=(30,0))
        ttk.Button(self.btn_frame, text="取消勾选", command=self.deselect_all).pack(side="left", padx=2)
        ttk.Button(self.btn_frame, text="反选", command=self.inverse_select).pack(side="left", padx=2)

        # 新增批量勾选第一个按钮 & 删除已勾选按钮
        self.btn_batch_select_first = ttk.Button(top_frame, text="批量勾选第一个", command=self.default_select)
        self.btn_batch_select_first.pack(side="left", padx=(10,0))
        self.btn_delete_checked = ttk.Button(top_frame, text="删除已勾选", command=self.delete_checked)
        self.btn_delete_checked.pack(side="left", padx=(10,0))

        # Canvas for scrolling
        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(self.canvas_frame)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side="left", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0,0), window=self.inner_frame, anchor="nw")
        self.inner_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # 鼠标滚轮绑定
        self.inner_frame.bind("<Enter>", self._bind_mousewheel)
        self.inner_frame.bind("<Leave>", self._unbind_mousewheel)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        self.populate_groups()

    def _bind_mousewheel(self, event=None):
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, event=None):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        bbox = self.canvas.bbox("all")  # 获取滚动区域
        if bbox is None:
            return
        canvas_height = self.canvas.winfo_height()
        scrollable_height = bbox[3] - canvas_height
        if scrollable_height <= 0:
            return  # 内容不足以滚动，不响应滚轮
        if hasattr(event, "delta"):
            self.canvas.yview_scroll(-1*(event.delta//120), "units")
        else:
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

    def select_target_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.target_folder = folder
            self.lbl_target.config(text=folder)

    def populate_groups(self):
        for w in self.inner_frame.winfo_children():
            w.destroy()
        cols_per_row = 3
        pad_x = 10
        pad_y = 10
        for idx, group in enumerate(self.groups):
            frame = ttk.LabelFrame(self.inner_frame, text=f"组 {idx+1}", padding=4)
            frame.grid(row=idx//cols_per_row, column=idx%cols_per_row, padx=pad_x, pady=pad_y, sticky="nw")
            self.selected[idx] = group[0]
            for pi in group:
                img = make_thumbnail(pi)
                if img is None:
                    img = Image.new('RGB', THUMB_SIZE, (200,200,200))
                tkimg = ImageTk.PhotoImage(img)
                self.thumb_cache[pi] = tkimg
                chk_var = tk.IntVar(value=1 if pi==group[0] else 0)
                chk = ttk.Checkbutton(frame, image=tkimg, variable=chk_var)
                chk.pack(side="left", padx=2, pady=2)
                chk.var = chk_var
                chk.path = pi
                chk.group_idx = idx
                chk.config(command=lambda c=chk: self.on_check(c))
                chk.bind("<Double-1>", lambda e, p=pi:self._open_file(p))
                chk.bind("<Button-3>", lambda e, p=pi:self._open_file_location(p))
                # 删除按钮
                btn_del = ttk.Button(frame, text="删除", command=lambda p=pi, cb=chk:self.delete_file(p, cb))
                btn_del.pack(side="left", padx=2, pady=2)

    def on_check(self, chk):
        idx = chk.group_idx
        if chk.var.get():
            self.selected[idx] = chk.path
        else:
            if self.selected.get(idx) == chk.path:
                self.selected[idx] = None

    def deselect_all(self):
        for child in self.inner_frame.winfo_children():
            for w in child.winfo_children():
                if hasattr(w, "var"):
                    w.var.set(0)
        self.selected = {}

    def inverse_select(self):
        for idx, group in enumerate(self.groups):
            for child in self.inner_frame.winfo_children():
                for w in child.winfo_children():
                    if hasattr(w, "var") and w.path in group:
                        w.var.set(0 if w.var.get() else 1)
                        if w.var.get(): self.selected[idx]=w.path
                        elif self.selected.get(idx)==w.path: self.selected[idx]=None

    def default_select(self):
        for idx, group in enumerate(self.groups):
            if not group:
                continue
            first_file = group[0]
            self.selected[idx] = first_file
            for child in self.inner_frame.winfo_children():
                if isinstance(child, ttk.LabelFrame) and child.cget("text") == f"组 {idx+1}":
                    for chk in child.winfo_children():
                        if isinstance(chk, ttk.Checkbutton):
                            chk.var.set(1 if chk.path == first_file else 0)

    def delete_checked(self):
        to_delete = []
        for idx, group in enumerate(self.groups):
            sel_file = self.selected.get(idx)
            if sel_file:
                to_delete.append((sel_file, idx))
        if not to_delete:
            messagebox.showinfo("提示", "没有已勾选的文件")
            return
        if not messagebox.askyesno("删除确认", f"确定要删除 {len(to_delete)} 个已勾选文件吗？"):
            return
        for path, idx in to_delete:
            try:
                os.remove(path)
            except Exception as e:
                messagebox.showerror("错误", f"删除失败: {path}\n{e}")
            # 从界面和缓存移除
            self.selected[idx] = None
            if path in self.thumb_cache:
                del self.thumb_cache[path]
        self.populate_groups()


    def delete_file(self, path, checkbox):
        if messagebox.askyesno("删除确认", f"确定要从磁盘删除 {os.path.basename(path)} 吗？"):
            try:
                os.remove(path)
                checkbox.master.destroy()
                if path in self.thumb_cache:
                    del self.thumb_cache[path]
                for idx in self.selected:
                    if self.selected[idx]==path:
                        self.selected[idx]=None
            except Exception as e:
                messagebox.showerror("错误", f"删除失败: {e}")

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

    def save_selected(self):
        if not self.target_folder:
            messagebox.showwarning("警告","请先选择目标文件夹")
            return
        if not os.path.exists(self.target_folder):
            os.makedirs(self.target_folder)
        if os.listdir(self.target_folder):
            if not messagebox.askyesno("提示", "目标文件夹不为空，是否清空？"):
                return
            for f in os.listdir(self.target_folder):
                fp = os.path.join(self.target_folder, f)
                try: shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
                except: pass

        dup_subfolder = os.path.join(self.target_folder, self.dup_subfolder_name)
        if not os.path.exists(dup_subfolder):
            os.makedirs(dup_subfolder)

        no_dup_files = [f for f in self.all_files if all(f not in g for g in self.groups)]
        for f in no_dup_files:
            shutil.copy2(f,self.target_folder)
        for idx, group in enumerate(self.groups):
            sel_file = self.selected.get(idx)
            for f in group:
                if f==sel_file:
                    shutil.copy2(f,self.target_folder)
                else:
                    shutil.copy2(f,dup_subfolder)
        messagebox.showinfo("完成","已保存选中图片")

class ImageDuplicateFinderApp:
    def __init__(self, root):
        self.root = root
        root.title("重复图片查找器 - 秋白")
        root.geometry("1200x700")
        self.current_folder = ""
        self.all_files = []
        self.filtered_files = []
        self.extensions = []
        self.thumb_cache = {}
        self.dedupe_thread = None
        self.dedupe_stop_event = None
        self.progress_queue = queue.Queue()
        self.thumb_visible = False
        self.duplicates = []

        # 顶部
        top_frame = ttk.Frame(root, padding=(8,8))
        top_frame.pack(side="top", fill="x")
        btn_select = ttk.Button(top_frame, text="选择文件夹", command=self.on_select_folder)
        btn_select.pack(side="left")
        self.lbl_folder = ttk.Label(top_frame, text="当前文件夹: (未选择)", width=70, anchor="w")
        self.lbl_folder.pack(side="left", padx=(8,8))
        btn_refresh = ttk.Button(top_frame, text="刷新扫描", command=self._rescan_current_folder)
        btn_refresh.pack(side="left", padx=(0,8))
        ttk.Label(top_frame, text="筛选类型:").pack(side="left", padx=(8,2))
        self.combo_ext = ttk.Combobox(top_frame, state="readonly", width=12)
        self.combo_ext.pack(side="left")
        self.combo_ext.bind("<<ComboboxSelected>>", lambda e: self.apply_filter_and_show_list())
        btn_show_thumbs = ttk.Button(top_frame, text="展示缩略图", command=self.on_show_thumbnails)
        btn_show_thumbs.pack(side="left", padx=(10,0))
        btn_find_dupes = ttk.Button(top_frame, text="查找重复项", command=self.on_find_duplicates)
        btn_find_dupes.pack(side="left", padx=(8,0))

        # 统计
        stats_frame = ttk.Frame(root, padding=(6,0))
        stats_frame.pack(side="top", fill="x")
        self.lbl_total = ttk.Label(stats_frame, text="总文件数: 0")
        self.lbl_total.pack(side="left", padx=(4,10))
        self.lbl_filtered = ttk.Label(stats_frame, text="筛选后文件数: 0")
        self.lbl_filtered.pack(side="left")

        # 主展示区
        main_frame = ttk.Frame(root)
        main_frame.pack(side="top", fill="both", expand=True)
        list_frame = ttk.Frame(main_frame, padding=(6,6))
        list_frame.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, columns=("name","ext","path"), show="headings")
        self.tree.heading("name", text="文件名")
        self.tree.heading("ext", text="后缀")
        self.tree.heading("path", text="路径")
        self.tree.column("name", width=400, anchor="w")
        self.tree.column("ext", width=80, anchor="center")
        self.tree.column("path", width=600, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree_scroll.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Button-3>", self.on_tree_right_click)
        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_command(label="打开文件", command=self.open_selected_file)
        self.menu.add_command(label="打开所在文件夹", command=self.open_file_location)

        # 缩略图展示区
        self.thumb_canvas_container = ttk.Frame(main_frame)
        self.thumb_canvas_container.pack(side="top", fill="both", expand=False)
        self.thumb_canvas_container.pack_forget()  # 默认隐藏
        self.thumb_canvas = tk.Canvas(self.thumb_canvas_container, height=200)
        self.thumb_canvas.pack(side="left", fill="both", expand=True)
        self.thumb_scroll = ttk.Scrollbar(self.thumb_canvas_container, orient="horizontal", command=self.thumb_canvas.xview)
        self.thumb_scroll.pack(side="bottom", fill="x")
        self.thumb_canvas.configure(xscrollcommand=self.thumb_scroll.set)
        self.thumb_frame = ttk.Frame(self.thumb_canvas)
        self.thumb_canvas.create_window((0,0), window=self.thumb_frame, anchor="nw")
        self.thumb_frame.bind("<Configure>", lambda e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")))
        self.thumb_canvas.bind("<Enter>", self._bind_thumb_mousewheel)
        self.thumb_canvas.bind("<Leave>", self._unbind_thumb_mousewheel)
        self.thumb_frame.bind("<Enter>", self._bind_thumb_mousewheel)
        self.thumb_frame.bind("<Leave>", self._unbind_thumb_mousewheel)

        # 底部
        bottom_frame = ttk.Frame(root, padding=(6,6))
        bottom_frame.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bottom_frame, orient="horizontal", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(4,4))
        self.lbl_progress_text = ttk.Label(bottom_frame, text="进度: 0% (0/0)")
        self.lbl_progress_text.pack(side="left", padx=(6,8))
        self.btn_stop = ttk.Button(bottom_frame, text="终止", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(4,4))
        self.root.after(200, self._poll_progress_queue)

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
            path = self.tree.item(selection[0])['values'][2]
            self._open_file(path)
    def open_file_location(self):
        selection = self.tree.selection()
        if selection:
            path = self.tree.item(selection[0])['values'][2]
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
        self.combo_ext['values'] = ["全部"] + exts
        self.combo_ext.current(0)
        self.apply_filter_and_show_list()

    # -------------------------- 筛选 / 列表显示 --------------------------
    def apply_filter_and_show_list(self):
        selected_ext = self.combo_ext.get()
        if selected_ext == "全部":
            self.filtered_files = [f for f in self.all_files if is_image_file(f)]
        else:
            self.filtered_files = [f for f in self.all_files if f.lower().endswith(selected_ext)]
        self.tree.delete(*self.tree.get_children())
        for f in self.filtered_files:
            self.tree.insert("", "end", values=(os.path.basename(f), os.path.splitext(f)[1].lower(), f))
        self.lbl_total.config(text=f"总文件数: {len(self.all_files)}")
        self.lbl_filtered.config(text=f"筛选后文件数: {len(self.filtered_files)}")

    # -------------------------- 缩略图 --------------------------
    def on_show_thumbnails(self):
        if self.thumb_visible:
            self.thumb_canvas_container.pack_forget()
            self.thumb_visible = False
        else:
            self.thumb_canvas_container.pack(side="top", fill="both", expand=False)
            self.thumb_visible = True
            threading.Thread(target=self._load_thumbnails_thread, daemon=True).start()
    def _load_thumbnails_thread(self):
        for widget in self.thumb_frame.winfo_children():
            widget.destroy()
        self.progress["maximum"] = len(self.filtered_files)
        self.progress["value"] = 0
        for idx, f in enumerate(self.filtered_files,1):
            if f in self.thumb_cache:
                tkimg = self.thumb_cache[f]
            else:
                img = make_thumbnail(f)
                if img is None:
                    img = Image.new('RGB', THUMB_SIZE, (200,200,200))
                tkimg = ImageTk.PhotoImage(img)
                self.thumb_cache[f]=tkimg
            lbl = tk.Label(self.thumb_frame, image=tkimg)
            lbl.image = tkimg
            lbl.path = f
            lbl.pack(side="left", padx=4, pady=4)
            lbl.bind("<Double-1>", lambda e, p=f:self._open_file(p))
            lbl.bind("<Button-3>", lambda e, p=f:self._open_file_location(p))
            self.progress["value"]=idx
            self.lbl_progress_text.config(text=f"加载缩略图: {idx}/{len(self.filtered_files)}")
        self.progress["value"]=0
        self.lbl_progress_text.config(text="缩略图加载完成")

    def _bind_thumb_mousewheel(self,event=None):
        self.thumb_canvas.bind_all("<MouseWheel>", self._on_thumb_mousewheel)
    def _unbind_thumb_mousewheel(self,event=None):
        self.thumb_canvas.unbind_all("<MouseWheel>")
    def _on_thumb_mousewheel(self,event):
        self.thumb_canvas.xview_scroll(-1*(event.delta//120), "units")

    # -------------------------- 重复查找 --------------------------
    def on_find_duplicates(self):
        if not self.filtered_files:
            messagebox.showinfo("提示","没有可处理文件")
            return
        if self.dedupe_thread and self.dedupe_thread.is_alive():
            messagebox.showwarning("警告","正在进行重复查找")
            return
        self.dedupe_stop_event = threading.Event()
        self.dedupe_thread = threading.Thread(target=dedupe_worker, args=(self.filtered_files,self.progress_queue,self.dedupe_stop_event), daemon=True)
        self.dedupe_thread.start()
        self.btn_stop.config(state="normal")

    def on_stop(self):
        if self.dedupe_stop_event:
            self.dedupe_stop_event.set()

    def _poll_progress_queue(self):
        try:
            while True:
                item = self.progress_queue.get_nowait()
                if item[0]=="progress":
                    processed,total = item[1], item[2]
                    self.progress["maximum"]=total
                    self.progress["value"]=processed
                    self.lbl_progress_text.config(text=f"重复查找: {processed}/{total}")
                elif item[0]=="result":
                    self.duplicates = item[1]
                elif item[0]=="done":
                    self.btn_stop.config(state="disabled")
                    self.progress["value"]=0
                    self.lbl_progress_text.config(text="重复查找完成")
                    if self.duplicates:
                        DuplicateGroupWindow(self.root,self.duplicates,self.all_files)
                    else:
                        messagebox.showinfo("提示","未发现重复图片")
                elif item[0]=="stopped":
                    self.btn_stop.config(state="disabled")
                    self.progress["value"]=0
                    self.lbl_progress_text.config(text="重复查找被终止")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_progress_queue)

if __name__=="__main__":
    root = tk.Tk()
    app = ImageDuplicateFinderApp(root)
    root.mainloop()
