import os
import json
import logging
import datetime
from typing import Optional, List, Dict, Any
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from supabase import create_client, Client

# Attempt to load secrets
SECRETS_FILE = "credentials.json"
supabase: Optional[Any] = None

def load_supabase_credentials():
    global supabase
    url = None
    key = None
    
    with open(SECRETS_FILE, 'r') as f:
        secrets = json.load(f)
        url = secrets.get("SUPABASE_URL")
        key = secrets.get("SUPABASE_ANON_KEY")

    if url and key:
        try:
            supabase = create_client(url, key)
            logging.info("Supabase client initialized.")
        except Exception as e:
            logging.error(f"Failed to initialize Supabase client: {e}")
    else:
        logging.warning("Supabase credentials not found. Functions will return recursion errors.")

load_supabase_credentials()

async def execute_get_habits(params: FunctionCallParams):
    days = params.arguments.get("days", 7)
    logging.info(f"Getting habits for past {days} days")
    
    if not supabase:
        await params.result_callback({"error": "Supabase client not initialized."})
        return

    try:
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=days)
        
        response = supabase.table("habits") \
            .select("*") \
            .gte("date", start_date.isoformat()) \
            .lte("date", today.isoformat()) \
            .execute()
            
        data = response.data
        
        # Flatten data: Group by date
        # { "2024-01-01": { "run": 30, "read": 10 }, ... }
        grouped_data = {}
        for entry in data:
            date = entry.get("date")
            habit = entry.get("habit_type")
            value = entry.get("value")
            
            if date not in grouped_data:
                grouped_data[date] = {}
            
            grouped_data[date][habit] = value

        formatted_result = f"[SYSTEM FETCHED DATA: HABITS]:\n\n{json.dumps(grouped_data, indent=2)}\n\n[END DATA]"
        await params.result_callback({"result": formatted_result})
        
    except Exception as e:
        logging.error(f"Error fetching habits: {e}")
        await params.result_callback({"error": str(e)})

get_habits_schema = FunctionSchema(
    name="get_habits",
    description="Get habit tracking data for the past N days. Includes current day.",
    properties={
        "days": {
            "type": "integer",
            "description": "Number of days into the past to retrieve. Default is 7.",
            "default": 7
        }
    },
    required=[]
)

async def execute_get_website_usage(params: FunctionCallParams):
    days = params.arguments.get("days", 7)
    logging.info(f"Getting website usage for past {days} days")
    
    if not supabase:
        await params.result_callback({"error": "Supabase client not initialized."})
        return

    try:
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=days)
        
        # Filter: timespent > 10 minutes (600 seconds)
        MIN_DURATION_SECONDS = 600
        
        response = supabase.table("website_usage") \
            .select("*") \
            .gte("date", start_date.isoformat()) \
            .lte("date", today.isoformat()) \
            .gt("timespent", MIN_DURATION_SECONDS) \
            .execute()

        data = response.data

        # Flatten data: Group by date
        # { "2024-01-01": { "google.com": 120, "github.com": 300 }, ... }
        grouped_data = {}
        for entry in data:
            date = entry.get("date")
            website = entry.get("website")
            timespent = entry.get("timespent")
            
            if date not in grouped_data:
                grouped_data[date] = {}
            
            grouped_data[date][website] = round(timespent / 60, 1)

        formatted_result = f"[SYSTEM FETCHED DATA: WEBSITE USAGE (Minutes)]:\n\n{json.dumps(grouped_data, indent=2)}\n\n[END DATA]"
        await params.result_callback({"result": formatted_result})

    except Exception as e:
        logging.error(f"Error fetching website usage: {e}")
        await params.result_callback({"error": str(e)})

get_website_usage_schema = FunctionSchema(
    name="get_website_usage",
    description="Get website usage data for the past N days. Filters for usage > 10 minutes. Returns values in minutes.",
    properties={
        "days": {
            "type": "integer",
            "description": "Number of days into the past to retrieve. Default is 7.",
            "default": 7
        }
    },
    required=[]
)
