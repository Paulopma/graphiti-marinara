@echo off
setlocal

pushd "%~dp0.."

echo Stopping Marinara Graphiti stack...
docker compose down
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo Failed to stop the stack cleanly.
  popd
  exit /b %EXIT_CODE%
)

popd
exit /b 0
