@echo off
REM CS2HQ 一键验收：后端测试(覆盖率门禁) + 前端类型检查 + Mock 全链路检查
REM 需先装依赖：backend/.venv 与 frontend/node_modules

cd /d %~dp0backend
.venv\Scripts\python.exe -m pytest --cov=app --cov-fail-under=89
if errorlevel 1 goto :fail

cd /d %~dp0frontend
call npx tsc --noEmit
if errorlevel 1 goto :fail

REM Mock 全链路：仅当 CS2HQ 后端已在 8100 运行时执行（预期输出 "pushed":true）
curl -s -m 3 http://127.0.0.1:8100/api/health | findstr /C:"ok" >nul
if %errorlevel%==0 (
  echo --- Mock 全链路检查 ---
  curl -s -X POST http://127.0.0.1:8100/api/test/mock-flow
  echo.
) else (
  echo [跳过] CS2HQ 后端未启动（8100），Mock 链路检查略过
)

echo VERIFY DONE
exit /b 0

:fail
echo VERIFY FAILED
exit /b 1
