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

def ensure_model_downloaded(model_name: str):
    print(f"Checking if model '{model_name}' is available...")
    try:
        # Check if model exists
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        if model_name not in result.stdout:
            print(f"Model '{model_name}' not found. Downloading...")
            subprocess.run(["ollama", "pull", model_name], check=True)
            print(f"Model '{model_name}' downloaded successfully.")
        else:
            print(f"Model '{model_name}' is already available.")
    except subprocess.CalledProcessError as e:
        print(f"Error checking/downloading model: {e}")
