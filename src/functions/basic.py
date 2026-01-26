import datetime
import urllib.request
import json
import asyncio
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

async def execute_get_current_time(params: FunctionCallParams):
    """Returns the current local time."""
    time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await params.result_callback(time_str)

get_current_time = FunctionSchema(
    name="get_current_time",
    description="Get the current local time in YYYY-MM-DD HH:MM:SS format",
    properties={},
    required=[]
)

async def execute_get_current_date(params: FunctionCallParams):
    """Returns the current date."""
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    await params.result_callback(date_str)

get_current_date = FunctionSchema(
    name="get_current_date",
    description="Get the current date in YYYY-MM-DD format",
    properties={},
    required=[]
)

async def execute_get_current_location(params: FunctionCallParams):
    """Returns the current location based on IP address."""
    try:
        # Run blocking I/O in a separate thread
        location = await asyncio.to_thread(_get_location_sync)
        await params.result_callback(location)
    except Exception as e:
        await params.result_callback(f"Location unavailable: {str(e)}")

def _get_location_sync() -> str:
    with urllib.request.urlopen("http://ip-api.com/json") as url:
        data = json.loads(url.read().decode())
        if data['status'] == 'success':
            return f"{data['city']}, {data['regionName']}, {data['country']}"
        else:
            return "Location unavailble"

get_current_location = FunctionSchema(
    name="get_current_location",
    description="Get the approximate location (city, region, country) based on IP address",
    properties={},
    required=[]
)
