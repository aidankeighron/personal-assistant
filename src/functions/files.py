import os
import asyncio
import logging
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
MEMORY_FILE = os.path.join(TOOLS_DIR, "memory.txt")

def _is_safe_path(path: str, base_dir: str) -> bool:
    """Ensures the path is within the base_dir."""
    return os.path.abspath(path).startswith(os.path.abspath(base_dir))

def _list_files_sync() -> str:
    try:
        files = [f for f in os.listdir(DATA_DIR) if os.path.isfile(os.path.join(DATA_DIR, f))]
        if not files:
            return "No files found in data directory."
        return "Available files:\n" + "\n".join(files)
    except Exception as e:
        return f"Error listing files: {str(e)}"

async def execute_list_files(params: FunctionCallParams):
    """Lists all files in the data directory."""
    logging.info("List files request")
    content = await asyncio.to_thread(_list_files_sync)
    logging.info(f"List files result: {content}")
    await params.result_callback(content)

list_files = FunctionSchema(
    name="list_files",
    description="Use this to see all available files in the data directory. No arguments required.",
    properties={},
    required=[]
)

async def execute_read_file(params: FunctionCallParams):
    """Reads content from a file in the data directory."""
    filename = params.arguments.get("filename")
    logging.info(f"Read file request for: {filename}")
    content = await asyncio.to_thread(_read_file_sync, filename)
    if content.startswith("Error"):
        logging.error(f"Read file error: {content}")
    else:
        logging.info(f"Successfully read file {filename}")
    await params.result_callback(content)

def _read_file_sync(filename: str) -> str:
    filepath = os.path.join(DATA_DIR, filename)
    
    if not _is_safe_path(filepath, DATA_DIR):
        return "Error: Access denied. Can only read files in the data directory."
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        available_files = _list_files_sync()
        return f"Error: File '{filename}' not found. {available_files}"
    except Exception as e:
        return f"Error reading file: {str(e)}"

read_file = FunctionSchema(
    name="read_file",
    description="Use this to read the entire contents of a file in the data directory. Do not add the /data prefix that is automatically applied.",
    properties={
        "filename": {
            "type": "string",
            "description": "The name of the file to read",
        }
    },
    required=["filename"]
)

async def execute_write_file(params: FunctionCallParams):
    """Writes content to a file in the data directory."""
    filename = params.arguments.get("filename")
    content = params.arguments.get("content")
    logging.info(f"Write file request for: {filename}")
    result = await asyncio.to_thread(_write_file_sync, filename, content)
    if result.startswith("Error"):
        logging.error(f"Write file error: {result}")
    else:
        logging.info(f"Successfully wrote to {filename}")
    await params.result_callback(result)

def _write_file_sync(filename: str, content: str) -> str:
    filepath = os.path.join(DATA_DIR, filename)
    
    if not _is_safe_path(filepath, DATA_DIR):
        return "Error: Access denied. Can only write files to the data directory."
        
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to '{filename}'."
    except Exception as e:
        return f"Error writing file: {str(e)}"

write_file = FunctionSchema(
    name="write_file",
    description="Use this to write content to a file in the data directory. Do not add the /data prefix that is automatically applied.",
    properties={
        "filename": {
            "type": "string",
            "description": "The name of the file to write to",
        },
        "content": {
            "type": "string",
            "description": "The content to write to the file",
        }
    },
    required=["filename", "content"]
)

async def execute_append_to_memory(params: FunctionCallParams):
    """Appends a new line to the memory.txt file."""
    content = params.arguments.get("content")
    logging.info(f"Append to memory request: {content}")
    result = await asyncio.to_thread(_append_to_memory_sync, content)
    if result.startswith("Error"):
         logging.error(f"Memory append error: {result}")
    else:
         logging.info("Successfully appended to memory")
    await params.result_callback(result)


def _append_to_memory_sync(content: str) -> str:
    try:
        with open(MEMORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n{content}")
        return f"Memory updated with: {content}"
    except Exception as e:
        return f"Error appending to memory: {str(e)}"

append_to_memory = FunctionSchema(
    name="append_to_memory",
    description="Use this to append a new line to your long-term memory file. Use this for remembering facts about the user, preferences, or important project details.",
    properties={
        "content": {
            "type": "string",
            "description": "The content to append to memory",
        }
    },
    required=["content"]
)
