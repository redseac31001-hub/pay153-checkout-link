@echo off
echo ==========================================
echo 验证服务配置
echo ==========================================
echo.

echo [1] 检查环境变量
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('  .env 配置:', os.getenv('PAYPAL_APPROVE_POLL_ATTEMPTS', '未设置'))"

echo.
echo [2] 检查运行时配置
python -c "import stripe_checkout as sc; print('  运行时配置:', sc.paypal_approve_poll_attempts())"

echo.
echo [3] 检查进程
tasklist | findstr python.exe

echo.
echo ==========================================
echo 验证完成
echo ==========================================
echo.
echo 期望结果：
echo   - .env 配置: 12
echo   - 运行时配置: 12
echo   - 如果不一致，说明服务未重启
echo.
pause
