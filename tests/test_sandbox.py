import pytest
from unittest.mock import MagicMock
from src.functions import sandbox
from pipecat.services.llm_service import FunctionCallParams

import asyncio

def mock_params(code):
    params = MagicMock(spec=FunctionCallParams)
    params.arguments = {"code": code}
    params.result_callback = MagicMock(return_value=asyncio.Future())
    params.result_callback.return_value.set_result(None)
    return params

@pytest.mark.asyncio
async def test_execute_run_python_code_success():
    code = "print(5 + 5)"
    params = mock_params(code)
    
    await sandbox.execute_run_python_code(params)
    
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    # Check that output is captured
    assert "10" in result

@pytest.mark.asyncio
async def test_execute_run_python_code_forbidden_import():
    code = "import os\nprint(os.getcwd())"
    params = mock_params(code)
    
    await sandbox.execute_run_python_code(params)
    
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert "Error" in result
    assert "Import of 'os' is not allowed" in result

@pytest.mark.asyncio
async def test_execute_run_python_code_math_library():
    code = "import math\nprint(math.sqrt(16))"
    params = mock_params(code)
    
    await sandbox.execute_run_python_code(params)
    
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert "4.0" in result
