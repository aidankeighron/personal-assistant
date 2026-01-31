import pytest
from unittest.mock import MagicMock, patch
from src.functions import google_ops
from pipecat.services.llm_service import FunctionCallParams
import asyncio

def mock_params(args=None):
    params = MagicMock(spec=FunctionCallParams)
    params.arguments = args or {}
    params.result_callback = MagicMock(return_value=asyncio.Future())
    params.result_callback.return_value.set_result(None)
    return params

@pytest.mark.asyncio
@patch("src.functions.google_ops._get_creds")
@patch("src.functions.google_ops.build")
async def test_execute_get_recent_emails(mock_build, mock_get_creds):
    # Mock Gmail service
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_get_creds.return_value = MagicMock()

    # Mock list messages
    mock_service.users().messages().list().execute.return_value = {
        'messages': [{'id': '123'}]
    }

    # Mock get message details
    mock_service.users().messages().get().execute.return_value = {
        'snippet': 'This is a test email snippet',
        'payload': {
            'headers': [
                {'name': 'From', 'value': 'sender@example.com'},
                {'name': 'Date', 'value': 'Mon, 01 Jan 2024 10:00:00 +0000'},
                {'name': 'Subject', 'value': 'Test Subject'}
            ]
        },
        'labelIds': ['UNREAD']
    }

    params = mock_params({"limit": 1})
    await google_ops.execute_get_recent_emails(params)

    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]
    
    expected_email_info = "From: sender@example.com | Date: Mon, 01 Jan 2024 10:00:00 +0000 | Status: Unread | Subject: Test Subject | Snippet: This is a test email snippet"
    expected_output = f"[CTX: EMAILS - Natural Speech/No Lists]\n{expected_email_info}\n[END DATA]"
    
    assert result == expected_output

@pytest.mark.asyncio
@patch("src.functions.google_ops._get_creds")
@patch("src.functions.google_ops.build")
async def test_execute_get_calendar_events(mock_build, mock_get_creds):
    # Mock Calendar service
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_get_creds.return_value = MagicMock()

    # Mock list events
    mock_service.events().list().execute.return_value = {
        'items': [
            {
                'summary': 'Meeting',
                'start': {'dateTime': '2024-01-01T10:00:00Z'},
                'end': {'dateTime': '2024-01-01T11:00:00Z'},
                'location': 'Office',
                'description': 'Discussion'
            }
        ]
    }

    params = mock_params({"days": 1})
    await google_ops.execute_get_calendar_events(params)

    params.result_callback.assert_called_once()
    result = params.result_callback.call_args[0][0]

    expected_event_info = "Event: Meeting\nStart: 2024-01-01T10:00:00Z\nEnd: 2024-01-01T11:00:00Z\nLocation: Office\nDescription: Discussion"
    expected_output = f"[CTX: CALENDAR - Natural Speech/No Lists]\n{expected_event_info}\n[END DATA]"

    assert result == expected_output
