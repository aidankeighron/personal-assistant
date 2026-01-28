import sys
import io
import contextlib
import logging
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

async def execute_run_python_code(params: FunctionCallParams):
    """
    Executes Python code in a restricted environment.
    """
    code = params.arguments.get("code")
    logging.info(f"Executing sandboxed python code: {code}")
    
    # Allowed modules
    safe_modules = {
        'math': __import__('math'),
        'random': __import__('random'),
        'datetime': __import__('datetime'),
        'json': __import__('json'),
    }

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in safe_modules:
            return safe_modules[name]
        raise ImportError(f"Import of '{name}' is not allowed")
    
    # Custom restricted builtins
    safe_builtins = {
        'abs': abs, 'all': all, 'any': any, 'ascii': ascii, 'bin': bin, 'bool': bool,
        'bytearray': bytearray, 'bytes': bytes, 'callable': callable, 'chr': chr,
        'complex': complex, 'dict': dict, 'divmod': divmod, 'enumerate': enumerate,
        'filter': filter, 'float': float, 'format': format, 'frozenset': frozenset,
        'getattr': getattr, 'hasattr': hasattr, 'hash': hash, 'hex': hex, 'id': id,
        'int': int, 'isinstance': isinstance, 'issubclass': issubclass, 'iter': iter,
        'len': len, 'list': list, 'map': map, 'max': max, 'min': min, 'next': next,
        'object': object, 'oct': oct, 'ord': ord, 'pow': pow, 'print': print,
        'range': range, 'repr': repr, 'reversed': reversed, 'round': round,
        'set': set, 'slice': slice, 'sorted': sorted, 'str': str, 'sum': sum,
        'tuple': tuple, 'type': type, 'zip': zip,
        '__import__': safe_import
    }

    # Restricted environment
    restricted_globals = {
        '__builtins__': safe_builtins,
    }

    # Capture output
    output_buffer = io.StringIO()
    result = ""
    try:
        # Redirect stdout and stderr
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
            exec(code, restricted_globals)
        result = output_buffer.getvalue()
    except Exception as e:
        result = f"Error: {e}"
        logging.error(f"Sandbox execution error: {result}")
    finally:
        output_buffer.close()
    
    logging.info(f"Sandbox execution result: {result}")
    await params.result_callback(result)

run_python_code = FunctionSchema(
    name="run_python_code",
    description="Use this to execute Python code in a sandboxed environment. The code cannot access the file system, network (except for safe modules), or unsafe builtins. Allowed modules: math, random, datetime, json. Input is a string of Python code. Returns stdout and stderr. Example: run_python_code(code='import math; print(math.sqrt(16))')",
    properties={
        "code": {
            "type": "string",
            "description": "The python code to execute",
        }
    },
    required=["code"]
)
