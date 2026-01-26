import sys
import os

# Set dummy API key for testing to prevent TavilyClient initialization error
os.environ["TAVILY_API_KEY"] = "test_key"

# Add the project root directory to sys.path
# This allows tests to import from src.functions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
