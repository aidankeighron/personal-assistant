from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from tavily import TavilyClient
import os

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

async def execute_web_search(params: FunctionCallParams):
    query = params.arguments.get("query")
    
    response = tavily.search(query=query, search_depth="basic", max_results=1)
    context = "\n".join([r["content"] for r in response["results"]])
    
    await params.result_callback({"result": context})

search_internet = FunctionSchema(
    name="search_internet",
    description="Search the internet for current information",
    properties={
        "query": {
            "type": "string",
            "description": "The search query.",
        }
    },
    required=["query"]
)