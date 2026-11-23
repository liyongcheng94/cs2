@echo off
REM CS2HQ 一键验收：后端测试(覆盖率门禁) + 前端类型检查
REM 需先装依赖：backend/.venv 与 frontend/node_modules
REM （Mock 全链路检查已随 /test/mock-flow 删除而移除）

cd /d %~dp0backend
.venv\Scripts\python.exe -m pytest --cov=app --cov-fail-under=87
if errorlevel 1 goto :fail

cd /d %~dp0frontend
call npx tsc --noEmit
if errorlevel 1 goto :fail

echo VERIFY DONE
exit /b 0

