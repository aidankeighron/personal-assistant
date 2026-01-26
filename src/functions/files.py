import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
MEMORY_FILE = os.path.join(TOOLS_DIR, "memory.txt")

def _is_safe_path(path: str, base_dir: str) -> bool:
    """Ensures the path is within the base_dir."""
    return os.path.abspath(path).startswith(os.path.abspath(base_dir))

def read_file(filename: str) -> str:
    """Reads content from a file in the data directory."""
    filepath = os.path.join(DATA_DIR, filename)
    
    if not _is_safe_path(filepath, DATA_DIR):
        return "Error: Access denied. Can only read files in the data directory."
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File '{filename}' not found."
    except Exception as e:
        return f"Error reading file: {str(e)}"

def write_file(filename: str, content: str) -> str:
    """Writes content to a file in the data directory."""
    filepath = os.path.join(DATA_DIR, filename)
    
    if not _is_safe_path(filepath, DATA_DIR):
        return "Error: Access denied. Can only write files to the data directory."
        
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to '{filename}'."
    except Exception as e:
        return f"Error writing file: {str(e)}"

def append_to_memory(content: str) -> str:
    """Appends a new line to the memory.txt file."""
    try:
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{content}\n")
        return "Successfully appended to memory."
    except Exception as e:
        return f"Error appending to memory: {str(e)}"
