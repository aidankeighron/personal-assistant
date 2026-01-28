# Personal Assistant

A voice-controlled AI assistant designed to run locally. This system leverages a local Large Language Model for intelligence and integrates with various external services and system tools to automate tasks and manage productivity.

## Features

- **Local Processing**: Uses Ollama for local LLM inference and a local Text-to-Speech engine for low-latency voice interaction.
- **Voice Interface**: Real-time speech-to-text and text-to-speech capabilities.
- **Tools & Integrations**:
  - **Google Workspace**: Reads emails and manages calendar events.
  - **System Control**: Checks resource usage, manages files, and executes Python code in a sandbox.
  - **Web Browser Control**: Blocks distracting websites via a companion Chrome extension.
  - **Memory**: Maintains a persistent memory interface to recall user preferences and past interactions.
  - **Self-Scheduling**: Can schedule prompts to remind or check in with the user at future times.
  - **Database**: Syncs habit and tracking data with Supabase.

## Setup

### Prerequisites
- **Python**: Ensure Python 3.10+ is installed.
- **Ollama**: Install Ollama and pull the model specified in `src/config.py` (default: `qwen3:4b-instruct-2507-q4_K_M`).
- **uv**: This project uses `uv` for dependency management.

### Installation

1. Clone the repository.
2. Install dependencies:
   ```bash
   uv sync
   ```

### Configuration

1. **Environment Variables**: Create a `.env` file in the root directory with the necessary API keys (e.g., `TAVILY_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`).
2. **Google Credentials**: Place your `google_credentials.json` file in the `tools/` directory to enable Gmail and Calendar features.
3. **Chrome Extension**:
   - Open Chrome and navigate to `chrome://extensions`.
   - Enable "Developer mode".
   - Click "Load unpacked" and select the `chrome-extension` directory from this project.

## Usage

To start the assistant:

```bash
uv run src/main.py
```

### Creating an Alias

You can verify the assistant is running by saying the wake word ("Jarvis").

To run the assistant from any directory, you can create a shell alias. Replace `<path-to-project>` with the absolute path to this directory.

**PowerShell**
Add this function to your PowerShell profile (`$PROFILE`):
```powershell
function jarvis {
    uv run --directory "<path-to-project>" src/main.py
}
```

**Bash / Zsh**
Add this alias to your `.bashrc` or `.zshrc`:
```bash
alias jarvis='uv run --directory "<path-to-project>" src/main.py'
```