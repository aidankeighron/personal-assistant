from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from tavily import TavilyClient
import os, psutil, logging

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

async def execute_web_search(params: FunctionCallParams):
    query = params.arguments.get("query")

    logging.info(f"Searching: {query}")
    response = tavily.search(query=query, search_depth="basic", max_results=1)
    context = "\n".join([r["content"] for r in response["results"]])
    logging.info(f"Got results: {context}")
    
    formatted_result = f"[CTX: WEB SEARCH]\n{context}\n[END DATA]"
    await params.result_callback({"result": formatted_result})

search_internet = FunctionSchema(
    name="search_internet",
    description="Use this to search the internet for any additional information. Make sure to provide a descriptive search query, e.g., 'current weather in Lansing Michigan' instead of 'current weather'.",
    properties={
        "query": {
            "type": "string",
            "description": "The search query.",
        }
    },
    required=["query"]
)

process = psutil.Process(os.getpid())
async def monitor_resources(params: FunctionCallParams):
    memory_info = process.memory_info()
    ram_used_mb = memory_info.rss / (1024 * 1024)

    logging.info("Requesting usage")
    process.cpu_percent(interval=0.1) 
    cpu_usage_percent = process.cpu_percent(interval=None)
    logging.info(f"Usage: CPU {cpu_usage_percent} RAM {ram_used_mb}")
    
    await params.result_callback({"ram": ram_used_mb, "cpu": cpu_usage_percent})

get_resource_usage = FunctionSchema(
    name="get_resource_usage",
    description="Use this to get the CPU and Memory usage of the program",
    properties={}, required=[]
)