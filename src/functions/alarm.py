from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
import asyncio
import datetime
import logging
import threading
from typing import Optional
from plyer import notification
import winsound
import time

# Store active alarms
active_alarms = {}
alarm_counter = 0

def _play_alarm_sound():
    sounds = [(150, 100), (300, 150), (500, 200), (300, 250)]

    for freq, dur in sounds:
        winsound.Beep(freq, dur)
        time.sleep(dur / 1000.0)

if __name__ == "__main__":
    _play_alarm_sound()

async def _trigger_alarm(alarm_id: int, alarm_name: str, scheduled_time: str):
    logging.info(f"Alarm triggered: {alarm_name} (ID: {alarm_id})")
    
    notification.notify(title=f"⏰ Alarm: {alarm_name}", message=f"Scheduled for {scheduled_time}", app_name="Personal Assistant", timeout=10)
    
    sound_thread = threading.Thread(target=_play_alarm_sound)
    sound_thread.start()
    
    if alarm_id in active_alarms:
        del active_alarms[alarm_id]

async def _schedule_alarm_task(alarm_id: int, delay_seconds: float, alarm_name: str, scheduled_time: str):
    try:
        await asyncio.sleep(delay_seconds)
        await _trigger_alarm(alarm_id, alarm_name, scheduled_time)
    except asyncio.CancelledError:
        logging.info(f"Alarm {alarm_id} ({alarm_name}) was cancelled")
        raise

def _parse_time_input(time_str: str) -> Optional[datetime.datetime]:
    time_str = time_str.strip()
    
    try:
        time_obj = datetime.datetime.strptime(time_str, "%H:%M").time()
        now = datetime.datetime.now()
        target = datetime.datetime.combine(now.date(), time_obj)
        
        if target <= now:
            target += datetime.timedelta(days=1)
        
        return target
    except ValueError:
        pass
    
    try:
        time_obj = datetime.datetime.strptime(time_str, "%I:%M %p").time()
        now = datetime.datetime.now()
        target = datetime.datetime.combine(now.date(), time_obj)
        
        if target <= now:
            target += datetime.timedelta(days=1)
        
        return target
    except ValueError:
        pass
    
    return None

async def execute_schedule_alarm(params: FunctionCallParams):
    global alarm_counter
    
    alarm_name = params.arguments.get("alarm_name", "Alarm")
    time_str = params.arguments.get("time")
    minutes = params.arguments.get("minutes")
    hours = params.arguments.get("hours")
    
    logging.info(f"Scheduling alarm: {alarm_name}, time={time_str}, minutes={minutes}, hours={hours}")
    
    now = datetime.datetime.now()
    target_time = None
    delay_seconds = 0
    
    if time_str:
        target_time = _parse_time_input(time_str)
        if not target_time:
            error_msg = f"Could not parse time '{time_str}'. Use format HH:MM (24-hour) or HH:MM AM/PM"
            logging.error(error_msg)
            await params.result_callback({"error": error_msg})
            return
        
        delay_seconds = (target_time - now).total_seconds()
        scheduled_time_str = target_time.strftime("%I:%M %p on %Y-%m-%d")
    elif minutes is not None or hours is not None:
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
