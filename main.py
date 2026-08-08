"""重复图片查找器 - 入口文件。"""

import tkinter as tk

from app.ui.main_window import ImageDuplicateFinderApp


def main():
    root = tk.Tk()
    ImageDuplicateFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
