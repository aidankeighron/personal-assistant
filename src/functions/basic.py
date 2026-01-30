import datetime
import urllib.request
import json
import asyncio
import logging
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

async def execute_get_date_time_location(params: FunctionCallParams):
    """Returns the current date, time, and location."""
    logging.info("Calling get_date_time_location")
    
    # Get time and date
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    # Get location (in a separate thread as it involves I/O)
    try:
        location = await asyncio.to_thread(_get_location_sync)
    except Exception as e:
        location = f"Unavailable ({str(e)})"
        
    result_str = f"Date: {date_str}\nTime: {time_str}\nLocation: {location}"
    logging.info(f"get_date_time_location result: {result_str}")
    await params.result_callback(result_str)

def _get_location_sync() -> str:
    try:
        with urllib.request.urlopen("http://ip-api.com/json", timeout=5) as url:
            data = json.loads(url.read().decode())
            if data['status'] == 'success':
                return f"{data['city']}, {data['regionName']}, {data['country']}"
            else:
                return "Location unavailable"
    except Exception as e:
        return f"Location unavailable ({str(e)})"

get_date_time_location = FunctionSchema(
    name="get_date_time_location",
    description="Use this to get the current date, time, and approximate location of the user.",
    properties={},
    required=[]
)
