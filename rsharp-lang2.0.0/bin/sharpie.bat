@echo off
set PYTHONPATH=%~dp0..
if "%1"=="new" (python -m rsharp pkg new game %2 %3 %4) else if "%1"=="install" (python -m rsharp pkg add %2 %3 %4) else (python -m rsharp pkg %*)
