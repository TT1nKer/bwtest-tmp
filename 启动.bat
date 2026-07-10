@echo off
chcp 65001 >nul
title 宽带下行测试工具
echo ================================
echo   宽带下行测试工具 v1.0
echo ================================
echo.
echo 启动中...
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

:: Run the program
python main.py

pause
