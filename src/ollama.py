import time, subprocess, urllib.request, urllib.error

def ensure_ollama_running():
    url = "http://localhost:11434/"
    try:
        urllib.request.urlopen(url)
        print("Ollama is already running.")
        return
    except (urllib.error.URLError, ConnectionRefusedError):
        print("Ollama is not running. Starting it...")
        subprocess.Popen(["ollama", "serve"], shell=True)

        print("Waiting for Ollama to become ready...", end="", flush=True)
        retries = 20
        while retries > 0:
            try:
                urllib.request.urlopen(url)
                print("\nOllama is ready!")
                return
            except (urllib.error.URLError, ConnectionRefusedError):
                time.sleep(1)
                print(".", end="", flush=True)
                retries -= 1