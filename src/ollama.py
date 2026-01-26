import time, subprocess, urllib.request, urllib.error, logging, json

def ensure_ollama_running():
    url = "http://localhost:11434/"
    try:
        urllib.request.urlopen(url)
        print("Ollama is already running.")
        logging.info("Ollama is already running.")
        return
    except (urllib.error.URLError, ConnectionRefusedError):
        print("Ollama is not running. Starting it...")
        logging.info("Ollama is not running. Starting it...")
        subprocess.Popen(["ollama", "serve"], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("Waiting for Ollama to become ready...", end="", flush=True)
        logging.info("Waiting for Ollama to become ready...")
        retries = 20
        while retries > 0:
            try:
                urllib.request.urlopen(url)
                print("\nOllama is ready!")
                logging.info("\nOllama is ready!")
                return
            except (urllib.error.URLError, ConnectionRefusedError):
                time.sleep(1)
                print(".", end="", flush=True)
                retries -= 1

def ensure_model_downloaded(model_name: str):
    print(f"Checking if model '{model_name}' is available...")
    logging.info(f"Checking if model '{model_name}' is available...")
    try:
        # Check if model exists
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        if model_name not in result.stdout:
            logging.info(f"Model '{model_name}' not found. Downloading...")
            subprocess.run(["ollama", "pull", model_name], check=True)
            logging.info(f"Model '{model_name}' downloaded successfully.")
        else:
            print(f"Model '{model_name}' is already available.")
            logging.info(f"Model '{model_name}' is already available.")
    except subprocess.CalledProcessError as e:
        print(f"Error checking/downloading model: {e}")
        logging.error(f"Error checking/downloading model: {e}")

    # We send an empty generation request with keep_alive: -1 to load it into RAM indefinitely.
    print(f"Setting model '{model_name}' to keep_alive=-1 (indefinite)...")
    logging.info(f"Setting model '{model_name}' to keep_alive=-1")
    
    url = "http://localhost:11434/api/generate"
    data = json.dumps({"model": model_name, "keep_alive": -1}).encode("utf-8")
    
    try:
        urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})            
        print(f"Model '{model_name}' is now loaded and will stay in memory.")
        logging.info(f"Model '{model_name}' set to keep_alive=-1 successfully.")
    except Exception as e:
        print(f"Warning: Failed to set keep_alive for model: {e}")
        logging.error(f"Warning: Failed to set keep_alive for model: {e}")

def unload_model(model_name: str):
    print(f"Unloading model '{model_name}' from memory...")
    logging.info(f"Unloading model '{model_name}' from memory...")
    
    url = "http://localhost:11434/api/generate"
    data = json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8")
    
    try:
        urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        print(f"Model '{model_name}' has been unloaded.")
        logging.info(f"Model '{model_name}' unloaded successfully.")
    except Exception as e:
        print(f"Warning: Failed to unload model: {e}")
        logging.error(f"Warning: Failed to unload model: {e}")