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
        
        file_list_output = []
        for filename in files:
            filepath = os.path.join(DATA_DIR, filename)
            description = "No description"
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    if first_line:
                        description = first_line
            except Exception:
                pass
            file_list_output.append(f"- {filename}: {description}")

        return "[SYSTEM FETCHED DATA: FILE LIST]\n" + "Available files:\n" + "\n".join(file_list_output) + "\n[END DATA]"
    except Exception as e:
        return f"Error listing files: {str(e)}"

def _read_file_sync(filename: str) -> str:
    filepath = os.path.join(DATA_DIR, filename)
    
    if not _is_safe_path(filepath, DATA_DIR):
        return "Error: Access denied. Can only read files in the data directory."
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            return f"[SYSTEM FETCHED DATA: FILE CONTENT ({filename})]\n\n{content}\n\n[END DATA]"
    except FileNotFoundError:
        available_files = _list_files_sync()
        return f"Error: File '{filename}' not found. {available_files}"
    except Exception as e:
        return f"Error reading file: {str(e)}"

def _write_file_sync(filename: str, content: str, description: str) -> str:
    filepath = os.path.join(DATA_DIR, filename)
    
    if not _is_safe_path(filepath, DATA_DIR):
        return "Error: Access denied. Can only write files to the data directory."
        
    try:
        final_content = f"{description}\n{content}"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_content)
        return f"Successfully wrote to '{filename}'."
    except Exception as e:
        return f"Error writing file: {str(e)}"

async def execute_manage_file_system(params: FunctionCallParams):
    """Manages file system operations (read, write, list)."""
    action = params.arguments.get("action")
    filename = params.arguments.get("filename")
    content = params.arguments.get("content")
    description = params.arguments.get("description")

    logging.info(f"manage_file_system request: action={action}, filename={filename}")

    if action == "list":
        result = await asyncio.to_thread(_list_files_sync)
    elif action == "read":
        if not filename:
            result = "Error: filename is required for read action."
        else:
            result = await asyncio.to_thread(_read_file_sync, filename)
    elif action == "write":
        if not filename or not content or not description:
            result = "Error: filename, content, and description are required for write action."
        else:
            result = await asyncio.to_thread(_write_file_sync, filename, content, description)
    else:
        result = f"Error: Unknown action '{action}'"
    
    if result.startswith("Error"):
        logging.error(f"manage_file_system error: {result}")
    else:
        log_output = result[:500] + "..." if len(result) > 500 else result
        logging.info(f"manage_file_system success: {log_output}")
    
    await params.result_callback(result)

manage_file_system = FunctionSchema(
    name="manage_file_system",
    description="Use this tool to manage files in the long term memory. You can list, read, or write files.",
    properties={
        "action": {
            "type": "string",
            "enum": ["list", "read", "write"],
            "description": "The action to perform. List will list all available files and their descriptions, and read and write will let you read and write to the files"
        },
        "filename": {
            "type": "string",
            "description": "The name of the file (required for read/write)."
        },
        "content": {
            "type": "string",
            "description": "The content to write (required for write)."
        },
        "description": {
            "type": "string",
            "description": "A description of the file (required for write)."
        }
    },
    required=["action"]
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
