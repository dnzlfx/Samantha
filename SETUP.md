# Samantha v1.3.0 - Setup Guide

## Prerequisites

### System Requirements
- **OS**: Linux (tested on Arch Linux)
- **RAM**: Minimum 16GB (24GB+ recommended for larger models)
- **Python**: 3.9+
- **Ollama**: Must be installed and running
- **SSH**: Access to home lab server (optional for homelab features)

### Install Ollama

```bash
# Install Ollama (if not already installed)
curl https://ollama.ai/install.sh | sh

# Start Ollama service
sudo systemctl start ollama
sudo systemctl enable ollama

# Verify Ollama is running
systemctl status ollama
```

### Pull Required Models

```bash
# Pull models based on your available RAM

# For systems with 16-24GB RAM (Low tier):
ollama pull qwen2.5-coder:14b
ollama pull llama3.1:8b
ollama pull llava:13b
ollama pull mistral:7b-instruct

# For systems with 24-48GB RAM (Medium tier):
ollama pull qwen2.5-coder:32b
# (keep other models from low tier)

# For systems with 48GB+ RAM (High tier):
ollama pull llama3.1:70b
ollama pull llava:34b
# (plus qwen2.5-coder:32b and mistral:7b-instruct)
```

## Installation

### 1. Navigate to Project

```bash
cd /home/chris/samantha_v1
```

### 2. Install Python Dependencies

```bash
# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Create Required Directories

```bash
# Sandbox directory
mkdir -p /tmp/sam_sandbox

# Database directory (requires write permission)
sudo mkdir -p /mnt/ollama_storage
sudo chown $USER:$USER /mnt/ollama_storage
```

### 4. SSH Setup (Optional - for HomeLab features)

```bash
# Verify SSH keys exist
ls -la ~/.ssh/id_ed25519

# Test connection to home lab
ssh -i ~/.ssh/id_ed25519 root@192.168.1.100 "echo 'Connection OK'"
```

## Running Samantha

### Start Samantha

```bash
cd /home/chris/samantha_v1

# If using virtual environment
source venv/bin/activate

# Run Samantha
python sam.py

# Or make it executable
chmod +x sam.py
./sam.py
```

### First Run

On first run, Samantha will:
1. Show startup banner with Samantha v1.3.0 branding
2. Run system checks (Ollama, SSH, directories, resources)
3. Initialize database at `/mnt/ollama_storage/sam_brain.db`
4. Scan configured directories for file indexing
5. Display system telemetry panel
6. Enter conversation mode

## Usage Examples

### Basic Conversation

```
You: Qué es Python?
Sam: [Response using llama3.1 for research intent]
```

### Web Search with Complete Content Extraction

```
You: busca la letra de Bohemian Rhapsody
Sam: [Searches and summarizes results]

You: dame la letra completa
Sam: [Extracts FULL lyrics via web scraping and displays]
```

### Code Generation and Sandbox Testing

```
You: crea un script que calcule fibonacci
Sam: [Generates code using qwen2.5-coder]
🧪 Test code in sandbox? [y/n]: y
[Real-time output appears line by line]
✅ Code execution successful
```

### Home Lab Management

```
You: revisa el servidor 116 con df -h
Sam: [Executes safe command automatically, shows output]

You: reinicia docker en el servidor
⚠️  DANGEROUS COMMAND DETECTED
Execute this command? [y/n]: y
[Shows real-time output from remote server]
```

### Special Commands

```
/help              - Show all commands
/model llama3.1    - Manually switch model
/inject /path/to/file - Inject file into conversation context
/search <query>    - Force web search
/clear             - Clear conversation history
/telemetry         - Show system stats
/diagnostic        - Run homelab diagnostic
/quit              - Exit Sam
```

### File Context Injection

```
You: /inject /home/chris/projects/myapp/config.py
Sam: ✅ Injected 1234 characters from config.py

You: explica este archivo
Sam: [Analyzes the injected file content]
```

## Troubleshooting

### Ollama Not Connecting

```bash
# Check if Ollama is running
systemctl status ollama

# Restart Ollama
sudo systemctl restart ollama

# Check logs
journalctl -u ollama -f
```

### Database Permission Errors

```bash
# Fix database directory permissions
sudo chown -R $USER:$USER /mnt/ollama_storage
chmod 755 /mnt/ollama_storage
```

### SSH Connection Fails

```bash
# Test SSH connection manually
ssh -i ~/.ssh/id_ed25519 root@192.168.1.100

# If fails, Samantha will continue without homelab features
# (homelab is optional and non-critical)
```

### Import Errors

```bash
# Make sure all dependencies are installed
pip install -r requirements.txt

# If missing lxml for BeautifulSoup
pip install lxml

# If missing spacy (optional)
pip install spacy
python -m spacy download es_core_news_sm
```

## Configuration

### File Scanning Paths

Edit `/home/chris/samantha_v1/modules/rag.py`:

```python
DEFAULT_SCAN_PATHS = [
    str(Path.home() / "projects"),
    str(Path.home() / "documents"),
    # Add your custom paths
]
```

### Home Lab Server

Edit `/home/chris/samantha_v1/modules/homelab.py`:

```python
DEFAULT_HOST = "192.168.1.100"  # Change to your server IP
DEFAULT_USER = "root"           # Change to your user
```

### Model Selection

Models are automatically selected based on available RAM:
- Edit `MODEL_CONFIGS` in `/home/chris/samantha_v1/core/llm_manager.py` to customize

## Features Verification

### Test Web Search with Complete Extraction

1. Start Samantha
2. Input: `busca la letra de From The Start`
3. Input: `dame la letra completa`
4. **Expected**: Full lyrics extracted and displayed (not snippets)

### Test Code Sandbox with Real-time Output

1. Input: `crea un script que cuente del 1 al 10 con delays`
2. Choose to test in sandbox
3. **Expected**: See output appearing line by line in real-time

### Test Model Auto-Switching

1. Input: `qué es Docker?` (should use research model)
2. Input: `escribe una función de fibonacci` (should switch to coding model)
3. **Expected**: Different models used, context preserved

### Test HomeLab SSH

1. Input: `revisa el servidor 116 con free -h` (safe - auto-runs)
2. Input: `reinicia docker en el servidor` (dangerous - asks confirmation)
3. **Expected**: First runs immediately, second asks for permission

## Logs and Debugging

Sam logs use structured format with `[Sam]` prefix:

```
[17:30:45][INFO][sam.core.llm_manager] [Sam] Initialized ModelManager with medium tier
[17:30:46][INFO][sam.core.search_engine] [Sam] Query optimization: 'busca maduro' → 'Nicolás Maduro Venezuela noticias 2026'
```

Enable debug logging by editing `sam.py`:

```python
logging.basicConfig(
    level=logging.DEBUG,  # Change from INFO to DEBUG
    ...
)
```

## Next Steps

1. Run Samantha and verify all system checks pass
2. Try the example interactions above
3. Customize scan paths and server settings for your environment
4. Explore special commands with `/help`
