@echo off
setlocal
chcp 65001 >nul 2>&1
title Ajedrez vs IA

cd /d "%~dp0"

echo ============================================
echo   Ajedrez vs IA - Inicio automatico
echo ============================================
echo.

rem --- 1. Buscar Python ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if defined PY goto :found_py
where python >nul 2>nul && set "PY=python"
if defined PY goto :found_py

echo [ERROR] No se encontro Python en el PATH.
echo         Instala Python desde https://www.python.org/downloads/
echo         y marca la opcion "Add python.exe to PATH".
echo.
pause
exit /b 1

:found_py
echo [1/4] Python encontrado: & %PY% --version
echo.

rem --- 2. Crear entorno virtual si no existe ---
if exist ".venv\Scripts\python.exe" goto :venv_ok
echo [2/4] Creando entorno virtual .venv ...
%PY% -m venv .venv
if errorlevel 1 (
    echo [ERROR] No se pudo crear el entorno virtual.
    pause
    exit /b 1
)
goto :venv_done

:venv_ok
echo [2/4] Entorno virtual .venv ya existe.

:venv_done
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

rem --- 3. Instalar dependencias ---
echo [3/4] Instalando dependencias (requirements.txt) ...
"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo       Dependencias listas.
echo.

rem --- 4. Lanzar la aplicacion ---
echo [4/4] Iniciando Streamlit...
echo.
"%VENV_PY%" -m streamlit run GameChessGemini.py

echo.
echo La aplicacion se ha cerrado.
pause
exit /b 0
