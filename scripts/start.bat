@echo off
setlocal

pushd "%~dp0.."

echo Starting Marinara Graphiti stack...
docker compose up -d --build
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo Failed to start the stack.
  popd
  exit /b %EXIT_CODE%
)

echo.
echo Stack is starting. Check status with:
echo   docker compose ps
echo.
popd
exit /b 0
