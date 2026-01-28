import asyncio
import datetime
import logging
import os
import json
from typing import List, Dict
from urllib.parse import urlparse
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from plyer import notification

# Store active blocks
active_blocks: Dict[int, Dict] = {}
block_counter = 0

# Command file location - use current user's directory
COMMAND_FILE_PATH = r"C:\Users\Billy1301\Documents\Programming\Programs\personal-assistant"

def _normalize_domain(url_or_domain: str) -> str:
    """Extract clean domain from URL or domain string."""
    url_or_domain = url_or_domain.strip()
    
    # If it looks like a URL, parse it
    if "://" in url_or_domain:
        parsed = urlparse(url_or_domain)
        domain = parsed.netloc or parsed.path
    else:
        # Remove leading www. if present
        domain = url_or_domain
    
    # Remove www. prefix
    if domain.startswith("www."):
        domain = domain[4:]
    
    # Remove any trailing slashes or paths
    domain = domain.split('/')[0]
    
    return domain.lower()

def _write_command_file(command: Dict) -> None:
    """Write a command to the file that the extension will read."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(COMMAND_FILE_PATH), exist_ok=True)
        
        # Add timestamp for change detection
        command['timestamp'] = datetime.datetime.now().timestamp()
        
        # Write command file
        with open(COMMAND_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(command, f, indent=2)
        
        logging.info(f"Wrote command to {COMMAND_FILE_PATH}: {command}")
    except Exception as e:
        raise Exception(f"Error writing command file: {str(e)}")

def _show_notification(title: str, message: str) -> None:
    """Show desktop notification."""
    try:
        notification.notify(
            title=title,
            message=message,
            app_name="Personal Assistant",
            timeout=10
        )
    except Exception as e:
        logging.error(f"Error showing notification: {e}")

async def _trigger_unblock(block_id: int, domains: List[str], block_name: str) -> None:
    """Trigger unblocking - write unblock command to file."""
    logging.info(f"Auto-unblocking triggered: {block_name} (ID: {block_id})")
    
    try:
        # Write unblock command
        command = {
            "command": "unblock",
            "domains": domains,
            "block_id": block_id
        }
        _write_command_file(command)
        
        # Show notification
        domain_list = ", ".join(domains)
        _show_notification(
            title="🌐 Websites Unblocked",
            message=f"Access restored to: {domain_list}"
        )
    except Exception as e:
        logging.error(f"Error during auto-unblock: {e}")
    
    # Remove from active blocks
    if block_id in active_blocks:
        del active_blocks[block_id]

async def _unblock_task(block_id: int, delay_seconds: float, domains: List[str], block_name: str) -> None:
    """Background task that waits and triggers the unblock."""
    try:
        await asyncio.sleep(delay_seconds)
        await _trigger_unblock(block_id, domains, block_name)
    except asyncio.CancelledError:
        logging.info(f"Block {block_id} was cancelled")
        raise

async def execute_block_websites(params: FunctionCallParams) -> None:
    """Block specified websites for a given duration."""
    global block_counter
    
    websites = params.arguments.get("websites", [])
    minutes = params.arguments.get("minutes")
    hours = params.arguments.get("hours")
    
    logging.info(f"Blocking websites: {websites}, minutes={minutes}, hours={hours}")
    
    # Validate inputs
    if not websites:
        error_msg = "No websites specified to block"
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    if not isinstance(websites, list):
        websites = [websites]
    
    if minutes is None and hours is None:
        error_msg = "Must specify duration in minutes and/or hours"
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    # Normalize all domains
    domains = []
    for website in websites:
        try:
            domain = _normalize_domain(website)
            domains.append(domain)
        except Exception as e:
            logging.warning(f"Could not parse '{website}': {e}")
    
    if not domains:
        error_msg = "No valid domains to block"
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    # Calculate duration
    total_minutes = (minutes or 0) + (hours or 0) * 60
    delay_seconds = total_minutes * 60
    
    if delay_seconds <= 0:
        error_msg = "Duration must be positive"
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    # Calculate unblock timestamp
    now = datetime.datetime.now()
    unblock_time = now + datetime.timedelta(seconds=delay_seconds)
    unblock_timestamp = int(unblock_time.timestamp())
    unblock_time_str = unblock_time.strftime("%I:%M %p on %Y-%m-%d")
    
    # Create block ID
    block_counter += 1
    block_id = block_counter
    
    # Write block command to file
    try:
        command = {
            "command": "block",
            "domains": domains,
            "unblock_timestamp": unblock_timestamp,
            "block_id": block_id
        }
        _write_command_file(command)
    except Exception as e:
        error_msg = str(e)
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    # Schedule auto-unblock
    block_name = f"Block {', '.join(domains)}"
    task = asyncio.create_task(_unblock_task(block_id, delay_seconds, domains, block_name))
    
    active_blocks[block_id] = {
        "task": task,
        "domains": domains,
        "unblock_time": unblock_time_str,
        "name": block_name
    }
    
    # Show confirmation notification
    domain_list = ", ".join(domains)
    duration_str = f"{hours}h " if hours else ""
    duration_str += f"{minutes}m" if minutes else ""
    
    _show_notification(
        title="🚫 Websites Blocked",
        message=f"Blocked {domain_list} for {duration_str.strip()}"
    )
    
    result_msg = f"Blocked {domain_list} for {duration_str.strip()}. Will unblock at {unblock_time_str}. The Chrome extension will apply the block within a few seconds."
    logging.info(f"block_websites output: {result_msg}")
    await params.result_callback({
        "result": result_msg,
        "block_id": block_id,
        "domains": domains,
        "unblock_time": unblock_time_str
    })

block_websites_schema = FunctionSchema(
    name="block_websites",
    description="Block access to specified websites for a given duration to help the user focus. Websites will be blocked via Chrome extension and automatically unblocked after the time expires. The user must have the Personal Assistant Website Blocker Chrome extension installed.",
    properties={
        "websites": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of websites to block. Can be URLs (e.g., 'https://youtube.com') or domains (e.g., 'youtube.com', 'reddit.com'). Both www and non-www variants will be blocked."
        },
        "minutes": {
            "type": "integer",
            "description": "Number of minutes to block the websites. Can be combined with hours."
        },
        "hours": {
            "type": "integer",
            "description": "Number of hours to block the websites. Can be combined with minutes."
        }
    },
    required=["websites"]
)
