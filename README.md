# personal assistant

## Python

`uv run src/main.py`
`uv add <>`

## Alias

You can alias the command `jarvis` to execute the program from any directory. Replace `<path-to-project>` with the absolute path to your project folder (e.g., `C:\Users\Billy1301\Documents\Programming\Programs\personal-assistant`).

### PowerShell
Add the following to your PowerShell profile (find it by running `$PROFILE` in PowerShell):

```powershell
function jarvis {
    uv run --directory "<path-to-project>" src/main.py
}
```

### Bash / Zsh
Add the following to your `.bashrc` or `.zshrc`:

```bash
alias jarvis='uv run --directory "<path-to-project>" src/main.py'
```

## Rust

Commands
`cargo run`
`cargo add <>`
`cargo build`

### Links

**Voice**: https://huggingface.co/jgkawell/jarvis
**Qwen2.5**: https://ollama.com/library/qwen2.5/tags
**Qwen3**: https://ollama.com/library/qwen3/tags