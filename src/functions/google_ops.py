import os
import datetime
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import asyncio
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

# Define scopes for read-only access
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.readonly'
]

# Paths for credentials
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
CREDENTIALS_FILE = os.path.join(TOOLS_DIR, "google_credentials.json")
TOKEN_FILE = os.path.join(TOOLS_DIR, "google_token.json")

def _get_creds():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logging.error(f"Error refreshing token: {e}")
                creds = None
        
        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"Credentials file not found at {CREDENTIALS_FILE}. Please follow setup instructions.")
            
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
    return creds

def _get_recent_emails_sync(limit=50):
    try:
        creds = _get_creds()
        service = build('gmail', 'v1', credentials=creds, cache_discovery=False)

        # Call the Gmail API
        results = service.users().messages().list(userId='me', maxResults=limit, labelIds=['INBOX']).execute()
        messages = results.get('messages', [])

        logging.info(f"Found {len(messages)} emails in INBOX (limit={limit})")

        if not messages:
            return "No emails found."

        email_data = []
        for message in messages:
            msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
            date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date')
            snippet = msg.get('snippet', '')
            
            email_info = f"From: {sender} | Date: {date} | Subject: {subject} | Snippet: {snippet}"
            email_data.append(email_info)

        return "\n\n".join(email_data)

    except Exception as e:
        return f"Error fetching emails: {str(e)}"

async def execute_get_recent_emails(params: FunctionCallParams):
    """Fetches the last N emails from Gmail (default 5)."""
    limit = params.arguments.get("limit", 5)
    if isinstance(limit, str):
        try:
            limit = int(limit)
        except ValueError:
            limit = 5
            
    logging.info(f"Calling get_recent_emails with limit={limit}")
    result = await asyncio.to_thread(_get_recent_emails_sync, limit=limit)
    logging.info("get_recent_emails completed")
    await params.result_callback(result)

get_recent_emails = FunctionSchema(
    name="get_recent_emails",
    description="Get the most recent emails from the user's Gmail account. DEFAULT: 5. Use 'limit' to request fewer (e.g., 1 for most recent).",
    properties={
        "limit": {
            "type": "integer",
            "description": "The number of emails to retrieve. Default is 5. Set to 1 for just the latest email.",
        }
    },
    required=["limit"]
)

def _get_calendar_events_sync():
    try:
        creds = _get_creds()
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)

        # Calculate time range: -2 weeks to +2 months
        now = datetime.datetime.utcnow()
        start_time = (now - datetime.timedelta(weeks=2)).isoformat() + 'Z'  # 'Z' indicates UTC time
        end_time = (now + datetime.timedelta(days=60)).isoformat() + 'Z'

        logging.info(f"Fetching calendar events from {start_time} to {end_time}")

        events_result = service.events().list(
            calendarId='primary', 
            timeMin=start_time, 
            timeMax=end_time,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return "No upcoming events found."

        event_list = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', 'No Title')
            description = event.get('description', 'No Description')
            location = event.get('location', 'No Location')
            
            event_info = f"Event: {summary}\nStart: {start}\nEnd: {end}\nLocation: {location}\nDescription: {description}"
            event_list.append(event_info)

        return "\n\n".join(event_list)

    except Exception as e:
        return f"Error fetching calendar events: {str(e)}"

async def execute_get_calendar_events(params: FunctionCallParams):
    """Fetches calendar events for the last 2 weeks and next 2 months."""
    logging.info("Calling get_calendar_events")
    result = await asyncio.to_thread(_get_calendar_events_sync)
    logging.info("get_calendar_events completed")
    await params.result_callback(result)

get_calendar_events = FunctionSchema(
    name="get_calendar_events",
    description="Get Google Calendar events for the past 2 weeks and upcoming 2 months. Returns event title, time, location, and description.",
    properties={},
    required=[]
)
