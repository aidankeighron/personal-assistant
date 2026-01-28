import asyncio
import datetime
import logging
import threading
from typing import Optional
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from plyer import notification
import os

# Store active alarms
active_alarms = {}
alarm_counter = 0

def _play_alarm_sound():
    """Play alarm sound using Windows beep."""
    try:
        # Windows beep: frequency (Hz), duration (ms)
        import winsound
        # Play a sequence of beeps
        for _ in range(3):
            winsound.Beep(1000, 500)  # 1000 Hz for 500ms
            asyncio.sleep(0.2)
    except Exception as e:
        logging.error(f"Error playing alarm sound: {e}")

def _show_notification(title: str, message: str):
    """Show desktop notification."""
    try:
        notification.notify(
            title=title,
            message=message,
            app_name="Personal Assistant",
            timeout=10  # Notification stays for 10 seconds
        )
    except Exception as e:
        logging.error(f"Error showing notification: {e}")

async def _trigger_alarm(alarm_id: int, alarm_name: str, scheduled_time: str):
    """Trigger the alarm - play sound and show notification."""
    logging.info(f"Alarm triggered: {alarm_name} (ID: {alarm_id})")
    
    # Show notification
    _show_notification(
        title=f"⏰ Alarm: {alarm_name}",
        message=f"Scheduled for {scheduled_time}"
    )
    
    # Play sound in a separate thread to not block
    sound_thread = threading.Thread(target=_play_alarm_sound)
    sound_thread.start()
    
    # Remove from active alarms
    if alarm_id in active_alarms:
        del active_alarms[alarm_id]

async def _schedule_alarm_task(alarm_id: int, delay_seconds: float, alarm_name: str, scheduled_time: str):
    """Background task that waits and triggers the alarm."""
    try:
        await asyncio.sleep(delay_seconds)
        await _trigger_alarm(alarm_id, alarm_name, scheduled_time)
    except asyncio.CancelledError:
        logging.info(f"Alarm {alarm_id} ({alarm_name}) was cancelled")
        raise

def _parse_time_input(time_str: str) -> Optional[datetime.datetime]:
    """Parse time string in various formats (HH:MM, HH:MM AM/PM)."""
    time_str = time_str.strip()
    
    # Try parsing HH:MM (24-hour format)
    try:
        time_obj = datetime.datetime.strptime(time_str, "%H:%M").time()
        now = datetime.datetime.now()
        target = datetime.datetime.combine(now.date(), time_obj)
        
        # If time has passed today, schedule for tomorrow
        if target <= now:
            target += datetime.timedelta(days=1)
        
        return target
    except ValueError:
        pass
    
    # Try parsing HH:MM AM/PM (12-hour format)
    try:
        time_obj = datetime.datetime.strptime(time_str, "%I:%M %p").time()
        now = datetime.datetime.now()
        target = datetime.datetime.combine(now.date(), time_obj)
        
        # If time has passed today, schedule for tomorrow
        if target <= now:
            target += datetime.timedelta(days=1)
        
        return target
    except ValueError:
        pass
    
    return None

async def execute_schedule_alarm(params: FunctionCallParams):
    """Schedule an alarm at a specific time or after a delay."""
    global alarm_counter
    
    alarm_name = params.arguments.get("alarm_name", "Alarm")
    time_str = params.arguments.get("time")
    minutes = params.arguments.get("minutes")
    hours = params.arguments.get("hours")
    
    logging.info(f"Scheduling alarm: {alarm_name}, time={time_str}, minutes={minutes}, hours={hours}")
    
    now = datetime.datetime.now()
    target_time = None
    delay_seconds = 0
    
    # Determine target time based on input
    if time_str:
        # Schedule at specific time
        target_time = _parse_time_input(time_str)
        if not target_time:
            error_msg = f"Could not parse time '{time_str}'. Use format HH:MM (24-hour) or HH:MM AM/PM"
            logging.error(error_msg)
            await params.result_callback({"error": error_msg})
            return
        
        delay_seconds = (target_time - now).total_seconds()
        scheduled_time_str = target_time.strftime("%I:%M %p on %Y-%m-%d")
    
    elif minutes is not None or hours is not None:
        # Schedule after delay
        total_minutes = (minutes or 0) + (hours or 0) * 60
        delay_seconds = total_minutes * 60
        target_time = now + datetime.timedelta(seconds=delay_seconds)
        scheduled_time_str = target_time.strftime("%I:%M %p on %Y-%m-%d")
    
    else:
        error_msg = "Must specify either 'time' or 'minutes'/'hours'"
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    if delay_seconds <= 0:
        error_msg = "Alarm time must be in the future"
        logging.error(error_msg)
        await params.result_callback({"error": error_msg})
        return
    
    # Create alarm task
    alarm_counter += 1
    alarm_id = alarm_counter
    
    task = asyncio.create_task(_schedule_alarm_task(alarm_id, delay_seconds, alarm_name, scheduled_time_str))
    active_alarms[alarm_id] = {
        "task": task,
        "name": alarm_name,
        "scheduled_time": scheduled_time_str,
        "target_time": target_time
    }
    
    result_msg = f"Alarm '{alarm_name}' scheduled for {scheduled_time_str}"
    logging.info(f"schedule_alarm output: {result_msg}")
    await params.result_callback({"result": result_msg, "alarm_id": alarm_id})

schedule_alarm_schema = FunctionSchema(
    name="schedule_alarm",
    description="Schedule an alarm to go off at a specific time or after a delay. The alarm will play a sound and show a notification. You can specify either a specific time (e.g., '14:30' or '2:30 PM') OR a delay in minutes/hours.",
    properties={
        "alarm_name": {
            "type": "string",
            "description": "Name/description of the alarm (e.g., 'Meeting reminder', 'Take medicine'). Default is 'Alarm'.",
            "default": "Alarm"
        },
        "time": {
            "type": "string",
            "description": "Specific time to trigger alarm in HH:MM format (24-hour) or HH:MM AM/PM format (12-hour). Example: '14:30' or '2:30 PM'. Leave empty if using minutes/hours instead."
        },
        "minutes": {
            "type": "integer",
            "description": "Number of minutes from now to trigger alarm. Can be combined with hours. Leave empty if using specific time."
        },
        "hours": {
            "type": "integer",
            "description": "Number of hours from now to trigger alarm. Can be combined with minutes. Leave empty if using specific time."
        }
    },
    required=[]
)
