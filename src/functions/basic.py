import datetime
import urllib.request
import json
import asyncio

async def get_current_time() -> str:
    """Returns the current local time."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def get_current_date() -> str:
    """Returns the current date."""
    return datetime.datetime.now().strftime("%Y-%m-%d")

async def get_current_location() -> str:
    """Returns the current location based on IP address."""
    try:
        # Run blocking I/O in a separate thread
        return await asyncio.to_thread(_get_location_sync)
    except Exception as e:
        return f"Location unavailable: {str(e)}"

def _get_location_sync() -> str:
    with urllib.request.urlopen("http://ip-api.com/json") as url:
        data = json.loads(url.read().decode())
        if data['status'] == 'success':
            return f"{data['city']}, {data['regionName']}, {data['country']}"
        else:
            return "Location unavailble"
