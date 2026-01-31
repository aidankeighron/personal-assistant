import socket
import logging

class Config:
    def __init__(self, git_base_path, whisper_device, whisper_compute_type, ollama_num_ctx=16384):
        self.GIT_BASE_PATH = git_base_path
        self.WHISPER_DEVICE = whisper_device
        self.WHISPER_COMPUTE_TYPE = whisper_compute_type
        self.OLLAMA_NUM_CTX = ollama_num_ctx

# Configuration dictionary keyed by hostname
CONFIGS = {
    "Aidan-PC": Config(
        git_base_path=r"C:\Users\Billy1301\Documents\Programming\Programs",
        whisper_device="cuda",
        whisper_compute_type="float16",
        ollama_num_ctx=16384
    )
}

DEFAULT_CONFIG = Config(
    git_base_path="./",
    whisper_device="cpu",
    whisper_compute_type="int8",
    ollama_num_ctx=16384
)

def get_config() -> Config:
    hostname = socket.gethostname()
    config = CONFIGS.get(hostname, DEFAULT_CONFIG)
    logging.info(f"Loaded config for hostname: {hostname} (Using default: {hostname not in CONFIGS})")
    return config
