# dupy

用于查找并处理指定文件夹的重复图片, 基于感知哈希(ImageHash dHash)实现 

1. 点击`选择文件夹`选择目标文件夹, 可用`筛选类型`只看特定扩展名 
2. 点击「查找重复项」, 在分组窗口中勾选需要保留的图片 
3. 选择目标文件夹, 点击`保存选中图片`整理文件; 也可直接删除已勾选或单张图片 

## 快速开始 

> Python 3.10及以上 
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 打包为`.exe`文件

```bash
pyinstaller --onefile --noconsole --name dupy main.py
```
