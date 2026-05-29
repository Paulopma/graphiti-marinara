@echo off
setlocal enabledelayedexpansion

pushd "%~dp0.."

set "NEO4J_PASSWORD="
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="NEO4J_PASSWORD" set "NEO4J_PASSWORD=%%B"
  )
)

if "%NEO4J_PASSWORD%"=="" (
  echo NEO4J_PASSWORD was not found in the environment or .env file.
  echo Populate .env from .env.example before resetting the graph.
  popd
  exit /b 1
)

echo Ensuring Neo4j is running...
docker compose up -d neo4j
if not "%ERRORLEVEL%"=="0" (
  echo Unable to start Neo4j.
  popd
  exit /b %ERRORLEVEL%
)

echo Waiting briefly for Neo4j to accept queries...
timeout /t 10 /nobreak >nul

echo Clearing graph data while keeping the schema in place...
docker compose exec -T neo4j cypher-shell -u neo4j -p "%NEO4J_PASSWORD%" "MATCH (n) DETACH DELETE n;"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo Graph reset failed.
  popd
  exit /b %EXIT_CODE%
)

echo Graph reset complete.
popd
exit /b 0
