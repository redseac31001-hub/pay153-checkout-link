@echo off
REM PayPal 修复验证和重启脚本

echo ========================================
echo PayPal 白名单修复 - 完整重启流程
echo ========================================
echo.

cd /d E:\mygit\pay153-checkout-link

echo [1/6] 停止所有 Python 进程...
taskkill /F /IM python.exe >nul 2>&1
if errorlevel 1 (
    echo     没有运行中的 Python 进程
) else (
    echo     ✓ 已停止 Python 进程
)
timeout /t 2 >nul

echo.
echo [2/6] 删除 Python 缓存文件...
del /S /Q *.pyc >nul 2>&1
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1
echo     ✓ 已清理缓存

echo.
echo [3/6] 验证文件修改...
findstr /C:"GB" stripe_checkout.py | findstr /C:"PAYPAL_ORDER_COUNTRIES" >nul
if errorlevel 1 (
    echo     ✗ 错误: GB 不在白名单中！
    echo     请检查 stripe_checkout.py 文件是否正确修改
    pause
    exit /b 1
) else (
    echo     ✓ 文件已正确修改（包含 GB）
)

echo.
echo [4/6] 验证 Python 导入...
python verify_fix.py
if errorlevel 1 (
    echo.
    echo     ✗ Python 导入验证失败！
    echo     请手动检查问题
    pause
    exit /b 1
)

echo.
echo [5/6] 启动服务...
echo     正在启动 app.py...
start "pay153-checkout" python app.py

echo.
echo [6/6] 等待服务启动...
timeout /t 3 >nul

echo.
echo ========================================
echo ✓ 重启完成！
echo ========================================
echo.
echo 预期结果：
echo   - GB 代理不再回退到 DE/EUR
echo   - 日志显示: "Checkout=GB/GBP"
echo   - 不再出现 400 错误
echo.
echo 请测试 GB 代理并观察日志
echo ========================================
pause
