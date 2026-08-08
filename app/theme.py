"""Discord 风格的深色/浅色主题管理。

基于 ttk clam 主题实现 ttk 控件配色, 并通过 option database
与递归遍历处理 tk 原生控件 (Canvas / Label / Menu / Frame)。
"""

import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Segoe UI"
FONT_SIZE = 10

DARK = {
    "name": "深色",
    "bg": "#313338",          # 主背景
    "panel": "#2B2D31",       # 工具栏/面板
    "card": "#2B2D31",        # 卡片
    "input": "#383A40",       # 输入框
    "hover": "#3F4147",       # 悬停
    "active": "#404249",      # 选中/按下
    "border": "#1E1F22",      # 边框
    "text": "#DBDEE1",        # 正文
    "muted": "#949BA4",       # 次要文字
    "header": "#F2F3F5",      # 标题文字
    "accent": "#5865F2",      # Discord 蓝紫
    "accent_hover": "#4752C4",
    "danger": "#DA373C",
    "danger_hover": "#A12828",
    "success": "#23A55A",
    "scroll": "#3F4147",
    "trough": "#2B2D31",
    "placeholder": (54, 57, 63),
}

LIGHT = {
    "name": "浅色",
    "bg": "#FFFFFF",
    "panel": "#F2F3F5",
    "card": "#F2F3F5",
    "input": "#EBEDEF",
    "hover": "#E3E5E8",
    "active": "#D3D6DA",
    "border": "#DBDEE1",
    "text": "#313338",
    "muted": "#80848E",
    "header": "#060607",
    "accent": "#5865F2",
    "accent_hover": "#4752C4",
    "danger": "#DA373C",
    "danger_hover": "#A12828",
    "success": "#23A55A",
    "scroll": "#C4C9CE",
    "trough": "#F2F3F5",
    "placeholder": (226, 229, 232),
}

PALETTES = {
    "dark": DARK,
    "light": LIGHT,
}


class ThemeManager:
    """管理全局 ttk 样式并在深色/浅色之间切换。"""

    def __init__(self, root, theme_name="dark"):
        self.root = root
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._windows = [root]
        self.name = None
        self.palette = None
        self.set_theme(theme_name)

    # ------------------------------------------------------------------
    # 窗口登记与控件遍历
    # ------------------------------------------------------------------
    def register(self, window):
        """登记新建的 Toplevel 窗口, 切换主题时一并刷新。"""
        if window not in self._windows:
            self._windows.append(window)

    def apply_theme(self, widget=None):
        """把当前主题应用到指定控件树; 缺省时应用到所有登记的窗口。"""
        targets = [widget] if widget is not None else list(self._windows)
        for w in targets:
            try:
                if w.winfo_exists():
                    self._walk(w)
            except tk.TclError:
                pass

    def _walk(self, widget):
        """递归设置 tk 原生控件的颜色 (ttk 控件由样式自动更新)。"""
        p = self.palette
        cls = widget.winfo_class()
        if cls == "Canvas":
            widget.configure(bg=p["bg"], highlightbackground=p["border"],
                             highlightthickness=0)
        elif cls == "Label":
            widget.configure(bg=p["bg"], fg=p["text"])
        elif cls == "Menu":
            widget.configure(bg=p["panel"], fg=p["text"],
                             activebackground=p["hover"],
                             activeforeground=p["text"],
                             borderwidth=0, relief="flat")
        elif cls == "Frame":
            widget.configure(bg=p["bg"])
        for child in widget.winfo_children():
            self._walk(child)

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------
    def set_theme(self, name):
        if name not in PALETTES:
            raise ValueError(f"未知主题: {name}")
        self.name = name
        self.palette = PALETTES[name]
        self._configure_styles(self.palette)
        self._apply_option_db(self.palette)
        self.apply_theme()
        return self.name

    def toggle(self):
        """在深色/浅色之间切换, 返回切换后的主题名。"""
        next_name = "light" if self.name == "dark" else "dark"
        return self.set_theme(next_name)

    @property
    def is_dark(self):
        return self.name == "dark"

    # ------------------------------------------------------------------
    # 样式定义 (Discord 配色)
    # ------------------------------------------------------------------
    def _configure_styles(self, p):
        s = self.style
        s.configure(".", background=p["bg"], foreground=p["text"],
                    fieldbackground=p["input"], bordercolor=p["border"],
                    troughcolor=p["trough"], selectbackground=p["accent"],
                    selectforeground="#FFFFFF", font=(FONT_FAMILY, FONT_SIZE))

        # 框架 / 标签
        s.configure("TFrame", background=p["bg"])
        s.configure("Panel.TFrame", background=p["panel"])
        s.configure("Card.TFrame", background=p["card"])
        s.configure("TPanedwindow", background=p["border"],
                    sashwidth=6, sashrelief="flat")
        s.configure("TLabel", background=p["bg"], foreground=p["text"])
        s.configure("Panel.TLabel", background=p["panel"], foreground=p["text"])
        s.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
        s.configure("PanelMuted.TLabel", background=p["panel"], foreground=p["muted"])
        s.configure("Header.TLabel", background=p["bg"], foreground=p["header"],
                    font=(FONT_FAMILY, 13, "bold"))
        s.configure("PanelHeader.TLabel", background=p["panel"],
                    foreground=p["header"], font=(FONT_FAMILY, 12, "bold"))

        # 按钮
        s.configure("TButton", background=p["input"], foreground=p["text"],
                    bordercolor=p["border"], borderwidth=1,
                    padding=(10, 6), focusthickness=0,
                    font=(FONT_FAMILY, FONT_SIZE))
        s.map("TButton",
              background=[("pressed", p["active"]), ("active", p["hover"])],
              bordercolor=[("pressed", p["active"]), ("active", p["hover"])],
              foreground=[("disabled", p["muted"])])

        s.configure("Secondary.TButton", background=p["input"], foreground=p["text"],
                    bordercolor=p["border"], borderwidth=1,
                    padding=(10, 6), focusthickness=0,
                    font=(FONT_FAMILY, FONT_SIZE))
        s.map("Secondary.TButton",
              background=[("pressed", p["active"]), ("active", p["hover"])],
              bordercolor=[("pressed", p["active"]), ("active", p["hover"])],
              foreground=[("disabled", p["muted"])])

        s.configure("Accent.TButton", background=p["accent"], foreground="#FFFFFF",
                    bordercolor=p["accent"], borderwidth=1,
                    padding=(14, 7), focusthickness=0,
                    font=(FONT_FAMILY, FONT_SIZE, "bold"))
        s.map("Accent.TButton",
              background=[("pressed", p["accent_hover"]),
                          ("active", p["accent_hover"])],
              bordercolor=[("pressed", p["accent_hover"]),
                           ("active", p["accent_hover"])],
              foreground=[("disabled", "#9DA3B8")])

        s.configure("Danger.TButton", background=p["danger"], foreground="#FFFFFF",
                    bordercolor=p["danger"], borderwidth=1,
                    padding=(10, 5), focusthickness=0,
                    font=(FONT_FAMILY, FONT_SIZE))
        s.map("Danger.TButton",
              background=[("pressed", p["danger_hover"]),
                          ("active", p["danger_hover"])],
              bordercolor=[("pressed", p["danger_hover"]),
                           ("active", p["danger_hover"])])

        # 勾选框
        s.configure("TCheckbutton", background=p["bg"], foreground=p["text"],
                    padding=(4, 2), font=(FONT_FAMILY, FONT_SIZE))
        s.map("TCheckbutton",
              background=[("active", p["hover"])],
              foreground=[("disabled", p["muted"])])
        s.configure("Card.TCheckbutton", background=p["card"],
                    foreground=p["text"], padding=(2, 2),
                    font=(FONT_FAMILY, FONT_SIZE))
        s.map("Card.TCheckbutton",
              background=[("active", p["hover"])],
              foreground=[("disabled", p["muted"])])

        # 输入框 / 下拉框
        s.configure("TEntry", fieldbackground=p["input"], foreground=p["text"],
                    insertcolor=p["text"], bordercolor=p["border"],
                    padding=(6, 4))
        s.map("TEntry", bordercolor=[("focus", p["accent"])])

        s.configure("TCombobox", fieldbackground=p["input"],
                    background=p["input"], foreground=p["text"],
                    arrowcolor=p["text"], bordercolor=p["border"],
                    padding=(6, 4), font=(FONT_FAMILY, FONT_SIZE))
        s.map("TCombobox",
              fieldbackground=[("readonly", p["input"])],
              selectbackground=[("readonly", p["input"])],
              selectforeground=[("readonly", p["text"])],
              background=[("readonly", p["input"])],
              bordercolor=[("focus", p["accent"])])

        # 树形列表
        s.configure("Treeview", background=p["bg"], fieldbackground=p["bg"],
                    foreground=p["text"], bordercolor=p["border"],
                    borderwidth=0, rowheight=30, font=(FONT_FAMILY, FONT_SIZE))
        s.map("Treeview",
              background=[("selected", p["active"])],
              foreground=[("selected", p["header"])])
        s.configure("Treeview.Heading", background=p["panel"],
                    foreground=p["muted"], relief="flat", padding=(8, 8),
                    font=(FONT_FAMILY, FONT_SIZE, "bold"))
        s.map("Treeview.Heading",
              background=[("active", p["hover"]), ("pressed", p["active"])],
              foreground=[("active", p["text"])])

        # 滚动条 / 进度条 / 分隔线
        s.configure("Vertical.TScrollbar", background=p["scroll"],
                    troughcolor=p["trough"], borderwidth=0,
                    arrowcolor=p["text"], relief="flat")
        s.map("Vertical.TScrollbar", background=[("active", p["hover"])])
        s.configure("Horizontal.TScrollbar", background=p["scroll"],
                    troughcolor=p["trough"], borderwidth=0,
                    arrowcolor=p["text"], relief="flat")
        s.map("Horizontal.TScrollbar", background=[("active", p["hover"])])
        s.configure("Horizontal.TProgressbar", background=p["accent"],
                    troughcolor=p["input"], borderwidth=0, thickness=8)
        s.configure("TSeparator", background=p["border"])

        # 分组卡片
        s.configure("TLabelframe", background=p["card"],
                    bordercolor=p["border"], borderwidth=1, relief="solid")
        s.configure("TLabelframe.Label", background=p["card"],
                    foreground=p["text"], font=(FONT_FAMILY, FONT_SIZE, "bold"))

    def _apply_option_db(self, p):
        """为之后创建的 tk 原生控件提供默认颜色。"""
        root = self.root
        try:
            root.option_clear()
        except tk.TclError:
            pass
        root.option_add("*background", p["bg"])
        root.option_add("*foreground", p["text"])
        root.option_add("*selectBackground", p["accent"])
        root.option_add("*selectForeground", "#FFFFFF")
        root.option_add("*Menu.background", p["panel"])
        root.option_add("*Menu.foreground", p["text"])
        root.option_add("*Menu.activeBackground", p["hover"])
        root.option_add("*Menu.activeForeground", p["text"])
        root.option_add("*Menu.borderWidth", 0)
        root.option_add("*TCombobox*Listbox.background", p["input"])
        root.option_add("*TCombobox*Listbox.foreground", p["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
