#!/usr/bin/env bash
set -e

echo "============================================================"
echo " Biomni UI - Virtual Environment Setup (Linux)"
echo "============================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo
echo "[1/5] Creating virtual environment at $VENV_DIR..."
python3 -m venv "$VENV_DIR"

echo
echo "[2/5] Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo
echo "[3/5] Installing core dependencies..."
pip install --upgrade pip
pip install biomni langgraph python-dotenv

echo
echo "[4/5] Installing PyTorch..."
# Detect CUDA availability
if command -v nvidia-smi &> /dev/null; then
    CUDA_VERSION=$(nvidia-smi | grep "CUDA Version" | awk '{print $NF}' | cut -d. -f1)
    echo "Detected CUDA $CUDA_VERSION"
    if [ "$CUDA_VERSION" -ge 12 ]; then
        echo "Installing torch with CUDA 12.8 support..."
        pip install torch --index-url https://download.pytorch.org/whl/cu128
    elif [ "$CUDA_VERSION" -ge 11 ]; then
        echo "Installing torch with CUDA 11.8 support..."
        pip install torch --index-url https://download.pytorch.org/whl/cu118
    else
        echo "CUDA version too old, falling back to CPU-only torch..."
        pip install torch --index-url https://download.pytorch.org/whl/cpu
    fi
else
    echo "No GPU detected. Installing CPU-only torch..."
    pip install torch --index-url https://download.pytorch.org/whl/cpu
fi

echo
echo "[5/5] Upgrading pyarrow for NumPy 2.x compatibility..."
pip install "pyarrow>=14.0" --upgrade

echo
echo "============================================================"
echo " Setup complete!"
echo " To run the launcher:"
echo "   source venv/bin/activate"
echo "   python biomni_launcher.py"
echo "============================================================"
