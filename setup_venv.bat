@echo off
echo ============================================================
echo  Biomni UI - Virtual Environment Setup (Windows)
echo ============================================================

set VENV_DIR=%~dp0venv

echo.
echo [1/5] Creating virtual environment at %VENV_DIR%...
python -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo.
echo [2/5] Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"

echo.
echo [3/5] Installing core dependencies...
pip install --upgrade pip
pip install biomni langgraph python-dotenv
if errorlevel 1 (
    echo ERROR: Failed to install core dependencies.
    pause
    exit /b 1
)

echo.
echo [4/5] Installing PyTorch with CUDA 12.8 support...
pip install torch --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
    echo WARNING: CUDA torch install failed. Falling back to CPU-only torch...
    pip install torch
)

echo.
echo [5/5] Upgrading pyarrow for NumPy 2.x compatibility...
pip install "pyarrow>=14.0" --upgrade

echo.
echo ============================================================
echo  Setup complete!
echo  To run the launcher:
echo    venv\Scripts\activate
echo    python biomni_launcher.py
echo ============================================================
pause
