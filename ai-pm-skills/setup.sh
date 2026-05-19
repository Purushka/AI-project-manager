#!/usr/bin/env bash
set -euo pipefail

echo "=== ai-pm-skills Environment Setup ==="
echo ""

# Check Python
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
        echo "[WARN] Python $PY_VERSION found, but 3.11+ is required."
        echo "       Please install Python 3.11 or later."
    else
        echo "[OK] Python $PY_VERSION"
    fi
else
    echo "[ERROR] Python 3 not found. Please install Python 3.11+."
    exit 1
fi

# Check Git
if command -v git &>/dev/null; then
    echo "[OK] Git $(git --version | awk '{print $3}')"
else
    echo "[WARN] Git not found. Version control will not be available."
fi

# Check Node.js (optional, for OpenClaw)
if command -v node &>/dev/null; then
    NODE_VERSION=$(node --version)
    echo "[OK] Node.js $NODE_VERSION"
else
    echo "[INFO] Node.js not found. Install Node.js 22+ if needed for OpenClaw."
fi

# Check Ollama (optional)
if command -v ollama &>/dev/null; then
    echo "[OK] Ollama found (local embeddings available)"
else
    echo "[INFO] Ollama not found. Will fall back to OpenAI for embeddings."
    echo "       Install from: https://ollama.ai"
fi

echo ""
echo "--- Setting up Python virtual environment ---"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ -d "$VENV_DIR" ]; then
    echo "Virtual environment already exists at $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    echo "Created virtual environment at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate" 2>/dev/null || source "$VENV_DIR/Scripts/activate" 2>/dev/null

echo "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "[OK] Dependencies installed"

echo ""
echo "--- Setting up runtime data directory ---"

DATA_DIR="$HOME/.openclaw/workspace/ai-pm-data"
mkdir -p "$DATA_DIR"
mkdir -p "$DATA_DIR/files"
mkdir -p "$DATA_DIR/patterns"
echo "[OK] Data directory: $DATA_DIR"

# Generate default config if not exists
CONFIG_FILE="$DATA_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'CONFIGEOF'
{
  "llm_provider": "openai",
  "openai_base_url": "http://localhost:8080/v1",
  "openai_api_key": "sk-placeholder",
  "embedding_provider": "ollama",
  "default_model": "gpt-5.5",
  "model_overrides": {},
  "workspace_path": "~/.openclaw/workspace/ai-pm-data",
  "max_context_tokens": 150000,
  "context_budget": {
    "global_summary": 10000,
    "ancestor_chain": 20000,
    "shared_interfaces": 30000,
    "current_task": 60000
  },
  "clustering_checkpoints": [2, 4, 6, 9],
  "ollama_base_url": "http://localhost:11434",
  "ollama_model": "nomic-embed-text",
  "openai_embedding_model": "text-embedding-3-small"
}
CONFIGEOF
    echo "[OK] Default config written to $CONFIG_FILE"
else
    echo "[OK] Config already exists at $CONFIG_FILE"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Set your Anthropic API key: export ANTHROPIC_API_KEY=sk-..."
echo "  2. (Optional) Start Ollama: ollama serve && ollama pull nomic-embed-text"
echo "  3. Install skills: bash install_skills.sh"
echo "  4. Run tests: python -m pytest tests/ -v"
