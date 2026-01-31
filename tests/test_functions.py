import pytest
from unittest.mock import MagicMock, patch
from src.functions import functions
from pipecat.services.llm_service import FunctionCallParams

import asyncio

def mock_params(args=None):
    params = MagicMock(spec=FunctionCallParams)
    params.arguments = args or {}
    params.result_callback = MagicMock(return_value=asyncio.Future())
    params.result_callback.return_value.set_result(None)
    return params

@pytest.mark.asyncio
@patch("src.functions.functions.tavily")
async def test_execute_web_search(mock_tavily):
    # Mock Tavily response
    mock_tavily.search.return_value = {
        "results": [
            {"content": "Result 1"},
            {"content": "Result 2"}
        ]
    }
    
    query = "test query"
    params = mock_params({"query": query})
    await functions.execute_web_search(params)
    
    mock_tavily.search.assert_called_once_with(query=query, search_depth="basic", max_results=1)
    
    # Check that results are joined
    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    assert result == {"result": "[CTX: WEB SEARCH]\nResult 1\nResult 2\n[END DATA]"}

@pytest.mark.asyncio
async def test_monitor_resources():
    # We can test that the structure returned has ram and cpu keys
    # using the real psutil since it's local system info, or mock it if strictly unit testing.
    # Let's mock psutil to be safe and deterministic.
    with patch("src.functions.functions.process") as mock_process:
        mock_process.memory_info.return_value.rss = 104857600 # 100 MB
        mock_process.cpu_percent.return_value = 15.5
        
        params = mock_params()
        await functions.monitor_resources(params)
        
        params.result_callback.assert_called_once()
        result = params.result_callback.call_args[0][0]
        assert "ram" in result
        assert "cpu" in result
        assert result["ram"] == 100.0
        assert result["cpu"] == 15.5
