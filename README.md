# dupy

## 关于

用于查找并处理指定文件夹内重复图片的桌面工具, 基于感知哈希 (ImageHash dHash) 实现 

1. 点击「选择文件夹」选择目标文件夹, 可用「筛选类型」只看特定扩展名 
2. 点击「显示缩略图」预览图片, 可上下拖动分隔条调整预览区高度 
3. 点击「查找重复项」, 在分组窗口中勾选需要保留的图片 
4. 选择目标文件夹, 点击「保存选中图片」整理文件; 也可直接删除已勾选或单张图片 

## 依赖库

- Python 3.10+ 
- Pillow: 图片读取与缩略图（`pip install pillow`） 
- ImageHash: 感知哈希（`pip install imagehash`） 
- PyInstaller: 打包（`pip install pyinstaller`） 

## 打包命令

```bash
pyinstaller --onefile --noconsole --name dupy main.py
```
