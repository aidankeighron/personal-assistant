from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
import asyncio, logging

async def run_command(cmd_list, cwd=None):
    process = await asyncio.create_subprocess_exec(*cmd_list, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        logging.info(f"Command {' '.join(cmd_list)} failed: {stderr.decode()}")
    
    return stdout.decode().strip()

async def execute_agent_git_modification(params: FunctionCallParams):
    prompt = params.arguments.get("prompt")
    branch_name = params.arguments.get("branch_name")
    repo_path = params.arguments.get("repo_path")

    logging.info(f"Starting agent git modification. Branch: {branch_name}, Prompt: {prompt}, Repo: {repo_path}")
    await params.result_callback({"status": "processing", "message": f"Starting work on branch {branch_name} in {repo_path}..."})

    try:
        logging.info(f"Creating branch {branch_name}...")
        await run_command(["git", "checkout", "-B", branch_name], cwd=repo_path)

        logging.info("Running Gemini CLI...")
        await run_command(["gemini", prompt], cwd=repo_path)

        logging.info("Committing changes...")
        await run_command(["git", "add", "."], cwd=repo_path)
        try:
            await run_command(["git", "commit", "-m", f"Apply Gemini changes: {prompt}"], cwd=repo_path)
        except Exception as e:
            if "nothing to commit" in str(e):
                return {"status": "error", "error": "Gemini CLI made no changes to the code."}
            raise e

        logging.info("Pushing branch...")
        await run_command(["git", "push", "-u", "origin", branch_name], cwd=repo_path)

        logging.info("Creating PR...")
        pr_url = await run_command(
            ["gh", "pr", "create", "--title", f"Agent: {branch_name}", "--body", prompt, "--head", branch_name], 
            cwd=repo_path
        )
        
        logging.info(f"PR Created: {pr_url}")
        await params.result_callback({"status": "success", "pr_url": pr_url})
        return {"status": "success", "pr_url": pr_url}

    except Exception as e:
        error_msg = f"Operation failed: {str(e)}"
        logging.error(error_msg)
        await params.result_callback({"status": "error", "error": error_msg})
        return {"status": "error", "error": error_msg}

agent_git_modification = FunctionSchema(
    name="agent_git_modification",
    description="Creates a branch, modifies code via Gemini CLI, pushes changes, and opens a PR.",
    properties={
        "prompt": {"type": "string", "description": "Instruction for code modification."},
        "branch_name": {"type": "string", "description": "Name of the git branch."},
        "repo_path": {"type": "string", "description": "Absolute path to the repo."},
    },
    required=["prompt", "branch_name", "repo_path"]
)