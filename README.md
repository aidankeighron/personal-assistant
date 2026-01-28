# personal assistant

## Python

`uv run ./server/main.py`
`uv add <>`

## Rust

Commands
`cargo run`
`cargo add <>`
`cargo build`

### Links

**Voice**: https://huggingface.co/jgkawell/jarvis
**Qwen2.5**: https://ollama.com/library/qwen2.5/tags
**Qwen3**: https://ollama.com/library/qwen3/tags

## Aliases (Windows PowerShell)

To run `jarvis voice` and `jarvis text` from any directory, add this function to your PowerShell profile (`code $PROFILE`):

```powershell
function jarvis {
    $projectPath = "C:\Users\Billy1301\Documents\Programming\Programs\personal-assistant"
    if ($args[0] -eq 'text') {
        uv run "$projectPath\src\text.py"
    } elseif ($args[0] -eq 'voice') {
        uv run "$projectPath\src\voice.py"
    } else {
        Write-Host "Usage: jarvis [voice|text]"
    }
}
```

After saving, restart PowerShell or run `. $PROFILE`. Then you can use:
- `jarvis voice` (Standard Voice Mode)
- `jarvis text` (Silent Text-Terminal Mode)