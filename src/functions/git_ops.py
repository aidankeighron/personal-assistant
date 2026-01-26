import subprocess
import logging
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

async def execute_agent_git_modification(params: FunctionCallParams):
    """
    Creates a branch, runs Gemini CLI, and creates a PR.
    """
    prompt = params.arguments.get("prompt")
    branch_name = params.arguments.get("branch_name")
    repo_path = params.arguments.get("repo_path")

    logging.info(f"Starting agent git modification. Branch: {branch_name}, Prompt: {prompt}, Repo: {repo_path}")
    await params.result_callback({"status": "processing", "message": f"Starting work on branch {branch_name} in {repo_path}..."})

    try:
        # 1. Create a new branch
        logging.info(f"Creating branch {branch_name}...")
        subprocess.run(["git", "checkout", "-b", branch_name], check=True, capture_output=True, text=True, cwd=repo_path)

        # 2. Run Gemini CLI
        logging.info("Running Gemini CLI...")
        # Assuming 'gemini' CLI takes the prompt as a positional argument or via stdin. 
        # Adjust command based on actual CLI usage if different. 
        # Using simple positional arg for now based on request "Gemini CLI with its prompt".
        subprocess.run(["gemini", prompt], check=True, capture_output=True, text=True, cwd=repo_path)

        # 3. Commit changes
        # We add all changes because Gemini might have modified or created files.
        logging.info("Committing changes...")
        subprocess.run(["git", "add", "."], check=True, capture_output=True, text=True, cwd=repo_path)
        subprocess.run(["git", "commit", "-m", f"Apply Gemini changes for: {prompt}"], check=True, capture_output=True, text=True, cwd=repo_path)

        # 4. Create PR
        logging.info("Creating PR...")
        # Using gh cli
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
