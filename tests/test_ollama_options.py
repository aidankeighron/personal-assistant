from unittest.mock import MagicMock, patch
import json
import logging
from src import ollama

# Configure logging to show info
logging.basicConfig(level=logging.INFO)

@patch("src.ollama.urllib.request.urlopen")
@patch("src.ollama.urllib.request.Request")
@patch("src.ollama.subprocess.run")
def test_ensure_model_downloaded_passes_options(mock_run, mock_request, mock_urlopen):
    # Mock subprocess.run for 'ollama list'
    mock_run.return_value.stdout = "mistral-nemo"

    model_name = "mistral-nemo"
    options = {"num_ctx": 16384}

    ollama.ensure_model_downloaded(model_name, options=options)

    # Verify that Request was called with the correct JSON payload
    mock_request.assert_called()
    call_args = mock_request.call_args
    # call_args[1] contain keyword args like 'data'
    data_arg = call_args[1].get('data')
    
    # Decode data to inspect JSON
    payload = json.loads(data_arg.decode("utf-8"))
    
    assert payload["model"] == model_name
    assert "options" in payload
    assert payload["options"]["num_ctx"] == 16384
    print("Verification Passed: Options were correctly passed to Ollama API.")

if __name__ == "__main__":
    test_ensure_model_downloaded_passes_options()
