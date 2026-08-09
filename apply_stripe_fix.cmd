@echo off
chcp 65001 >nul
echo ========================================
echo Stripe API 版本升级补丁
echo ========================================
echo.

echo [1/4] 备份原文件...
copy stripe_checkout.py stripe_checkout.py.backup >nul 2>&1
if %errorlevel% == 0 (
    echo     ✓ 已备份到 stripe_checkout.py.backup
) else (
    echo     ✗ 备份失败，请检查文件是否存在
    pause
    exit /b 1
)
echo.

echo [2/4] 应用补丁...
powershell -Command "(Get-Content stripe_checkout.py -Encoding UTF8) -replace '2020-08-27;custom_checkout_beta=v1;', '2025-03-31.basil;' | Set-Content stripe_checkout.py -Encoding UTF8"
echo     ✓ 已更新 PAYPAL_STRIPE_VERSION
echo.

echo [3/4] 验证修改...
findstr /C:"2025-03-31.basil" stripe_checkout.py >nul
if %errorlevel% == 0 (
    echo     ✓ 补丁应用成功
    echo     ✓ API 版本已从 2020-08-27 升级到 2025-03-31.basil
) else (
    echo     ✗ 补丁应用失败
    echo     正在恢复备份...
    copy stripe_checkout.py.backup stripe_checkout.py >nul
    pause
    exit /b 1
)
echo.

echo [4/4] 检查是否有运行中的 Python 进程...
tasklist | findstr /I "python.exe" >nul
if %errorlevel% == 0 (
    echo     ⚠ 检测到运行中的 Python 进程
    echo     请手动停止服务后重新启动
    echo.
    echo     停止方法：taskkill /F /IM python.exe
) else (
    echo     ✓ 没有运行中的 Python 进程
)
echo.

echo ========================================
echo 补丁应用完成！
echo ========================================
echo.
echo 下一步操作：
echo.
echo 1. 重启服务：
echo    python app.py
echo.
echo 2. 运行 API 版本测试（推荐）：
echo    python test_stripe_api_versions.py "cs_live_xxxxx" "socks5://proxy:port"
echo.
echo 3. 执行完整提链测试：
echo    查看日志中是否显示 pm=['card', 'paypal']
echo.
echo 4. 如需回滚：
echo    copy stripe_checkout.py.backup stripe_checkout.py
echo.
echo ========================================
echo.
pause
