import sys
import io
import contextlib

def run_python_code(code: str) -> str:
    """
    Executes Python code in a restricted environment.
    Only allows access to safe modules like math, random, datetime.
    No file system or network access allowed.
    Returns the stdout and stderr captured during execution.
    """
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
    
    try:
        # Redirect stdout and stderr
        with contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
            exec(code, restricted_globals)
        return output_buffer.getvalue()
    except Exception as e:
        return f"Error: {e}"
    finally:
        output_buffer.close()
