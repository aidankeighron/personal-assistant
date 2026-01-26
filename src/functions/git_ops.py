import subprocess
import logging
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

async def execute_agent_git_modification(params: FunctionCallParams):
    prompt = params.arguments.get("prompt")
    branch_name = params.arguments.get("branch_name")
    repo_path = params.arguments.get("repo_path")

    logging.info(f"Starting agent git modification. Branch: {branch_name}, Prompt: {prompt}, Repo: {repo_path}")
    await params.result_callback({"status": "processing", "message": f"Starting work on branch {branch_name} in {repo_path}..."})

    try:
        logging.info(f"Creating branch {branch_name}...")
        subprocess.run(["git", "checkout", "-b", branch_name], check=True, capture_output=True, text=True, cwd=repo_path)

        logging.info("Running Gemini CLI...")
        subprocess.run(["gemini", prompt], check=True, capture_output=True, text=True, cwd=repo_path)

        logging.info("Committing changes...")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, text=True, cwd=repo_path)
        subprocess.run(["git", "commit", "-m", f"Apply Gemini changes for: {prompt}"], check=True, capture_output=True, text=True, cwd=repo_path)

        logging.info("Creating PR...")
        pr_result = subprocess.run(
            ["gh", "pr", "create", "--title", f"Agent modification: {branch_name}", "--body", prompt],
            check=True, capture_output=True, text=True, cwd=repo_path
        )
        
        pr_url = pr_result.stdout.strip()
        logging.info(f"PR Created: {pr_url}")

        await params.result_callback({"status": "success", "pr_url": pr_url})
        return {"status": "success", "pr_url": pr_url}

    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed: {e.cmd}. Output: {e.stderr}"
        logging.error(error_msg)
        await params.result_callback({"status": "error", "error": error_msg})
        return {"status": "error", "error": error_msg}
    except Exception as e:
        error_msg = f"An error occurred: {str(e)}"
        logging.error(error_msg)
        await params.result_callback({"status": "error", "error": error_msg})
        return {"status": "error", "error": error_msg}

agent_git_modification = FunctionSchema(
    name="agent_git_modification",
    description="creates a new branch, uses the gemini cli to edit code, and creates a PR",
    properties={
        "prompt": {
            "type": "string",
            "description": "The instruction for the Gemini CLI to modify the code.",
        },
        "branch_name": {
            "type": "string",
            "description": "The name of the new git branch to create.",
        },
        "repo_path": {
            "type": "string",
            "description": "The absolute path to the git repository.",
        },
    },
    required=["prompt", "branch_name", "repo_path"]
)
