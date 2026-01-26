import pytest
import datetime
import asyncio
from unittest.mock import MagicMock, patch
from src.functions import basic
from pipecat.services.llm_service import FunctionCallParams

# Mock FunctionCallParams
def mock_params(args=None):
    params = MagicMock(spec=FunctionCallParams)
    params.arguments = args or {}
    params.result_callback = MagicMock(return_value=asyncio.Future())
    params.result_callback.return_value.set_result(None)
    return params

@pytest.mark.asyncio
async def test_execute_get_current_time():
    params = mock_params()
    await basic.execute_get_current_time(params)
    
    # Check that result_callback was called with a time string
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert isinstance(result, str)
    # Basic format check (not strict on exact time)
    assert len(result.split(":")) == 3

@pytest.mark.asyncio
async def test_execute_get_current_date():
    params = mock_params()
    await basic.execute_get_current_date(params)
    
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert isinstance(result, str)
    assert len(result.split("-")) == 3

@pytest.mark.asyncio
@patch("urllib.request.urlopen")
async def test_execute_get_current_location_success(mock_urlopen):
    # Mocking the response from ip-api.com
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"status": "success", "city": "Test City", "regionName": "Test Region", "country": "Test Country"}'
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_response
    mock_context.__exit__.return_value = None
    mock_urlopen.return_value = mock_context
    
    params = mock_params()
    await basic.execute_get_current_location(params)
    
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert result == "Test City, Test Region, Test Country"

@pytest.mark.asyncio
@patch("urllib.request.urlopen")
async def test_execute_get_current_location_failure(mock_urlopen):
    # Mocking failure response
    mock_response = MagicMock()
    # Simulate a network error or invalid JSON causing exception or bad status
    mock_urlopen.side_effect = Exception("Network Error")
    
    params = mock_params()
    await basic.execute_get_current_location(params)
    
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert result.startswith("Location unavailable")
