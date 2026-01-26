import pytest
import os
from unittest.mock import MagicMock, patch, mock_open
from src.functions import files
from pipecat.services.llm_service import FunctionCallParams

def mock_params(args=None):
    params = MagicMock(spec=FunctionCallParams)
    params.arguments = args or {}
    params.result_callback = MagicMock(return_value=MagicMock())
    return params

@pytest.mark.asyncio
@patch("src.functions.files.DATA_DIR", "/mock/data")
@patch("os.path.abspath")
async def test_execute_read_file_success(mock_abspath):
    # Setup safe path checks
    mock_abspath.side_effect = lambda p: p.replace("\\", "/") # Simple normalization for test

    filename = "test.txt"
    with patch("builtins.open", mock_open(read_data="file content")) as mock_file:
        params = mock_params({"filename": filename})
        # Mock _is_safe_path to return True for this test
        with patch("src.functions.files._is_safe_path", return_value=True):
             await files.execute_read_file(params)
        
        params.result_callback.assert_called_once_with("file content")
        mock_file.assert_called_once()

@pytest.mark.asyncio
@patch("src.functions.files.DATA_DIR", "/mock/data")
async def test_execute_read_file_security_violation():
    filename = "../secret.txt"
    params = mock_params({"filename": filename})
    
    # We rely on the real _is_safe_path logic here if possible, but identifying ".." depends on os.path.abspath
    # Simplest way is to mock _is_safe_path to return False
    with patch("src.functions.files._is_safe_path", return_value=False):
        await files.execute_read_file(params)
    
    result = params.result_callback.call_args[0][0]
    assert "Access denied" in result

@pytest.mark.asyncio
@patch("src.functions.files.DATA_DIR", "/mock/data")
async def test_execute_write_file_success():
    filename = "test.txt"
    content = "new content"
    params = mock_params({"filename": filename, "content": content})
    
    with patch("builtins.open", mock_open()) as mock_file:
         with patch("src.functions.files._is_safe_path", return_value=True):
            await files.execute_write_file(params)
         
         mock_file.assert_called_once()
         handle = mock_file()
         handle.write.assert_called_once_with(content)
         params.result_callback.assert_called_once()
         assert "Successfully wrote" in params.result_callback.call_args[0][0]

@pytest.mark.asyncio
@patch("src.functions.files.MEMORY_FILE", "/mock/tools/memory.txt")
async def test_execute_append_to_memory():
    content = "Remember this"
    params = mock_params({"content": content})
    
    with patch("builtins.open", mock_open()) as mock_file:
        await files.execute_append_to_memory(params)
        
        mock_file.assert_called_once_with("/mock/tools/memory.txt", 'a', encoding='utf-8')
        handle = mock_file()
        handle.write.assert_called_once_with(f"\n{content}")
        params.result_callback.assert_called_once()
