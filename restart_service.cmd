@echo off
REM PayPal 提链服务重启脚本

echo ========================================
echo PayPal 提链服务重启
echo ========================================
echo.

echo [1/3] 停止旧服务...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *app.py*" 2>nul
timeout /t 2 /nobreak >nul

echo [2/3] 验证环境变量...
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('轮询次数:', os.getenv('PAYPAL_APPROVE_POLL_ATTEMPTS', '未设置'))"

echo.
echo [3/3] 启动新服务...
start "PayPal提链服务" python app.py

echo.
echo ========================================
echo 服务已重启
echo ========================================
echo.
echo 提示：
echo - 轮询次数已增加到 12 次
echo - 请重新运行提链任务
echo - 观察日志中的轮询成功次数
echo.

pause
