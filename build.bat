@echo off
chcp 65001 >nul
title 宽带下行测试 - 一键编译

echo ============================================
echo   宽带下行测试工具 - 编译打包
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未安装 Python，请先从 python.org 下载安装
    echo 安装时务必勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/3] 安装 PyInstaller...
pip install pyinstaller -q
if %errorlevel% neq 0 (
    echo [错误] PyInstaller 安装失败
    pause
    exit /b 1
)

echo [2/3] 清理旧文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 开始编译 exe（约 1-3 分钟）...
echo.

pyinstaller --onefile --windowed --name "宽带下行测试" ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import tkinter.messagebox ^
    --hidden-import tkinter.filedialog ^
    --hidden-import engine ^
    --hidden-import hashlib ^
    --hidden-import hmac ^
    --hidden-import json ^
    --hidden-import ssl ^
    --hidden-import struct ^
    --hidden-import threading ^
    --hidden-import concurrent.futures ^
    --hidden-import urllib.request ^
    --hidden-import platform ^
    --hidden-import subprocess ^
    --hidden-import re ^
    --hidden-import datetime ^
    --hidden-import tempfile ^
    --hidden-import pathlib ^
    --add-data "engine.py;." ^
    --clean --noconfirm ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 编译失败，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo ============================================
echo   编译成功！
echo   输出文件: dist\宽带下行测试.exe
echo ============================================
echo.
echo 将该 exe 复制给客户即可，无需安装 Python。
echo 客户右键"以管理员身份运行"即可使用。
echo.
pause
