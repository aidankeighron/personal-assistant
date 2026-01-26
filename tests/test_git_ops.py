import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os
import subprocess

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
from functions import git_ops

@pytest.mark.asyncio
async def test_execute_agent_git_modification_success():
    params = MagicMock()
    params.arguments = {"prompt": "Fix bug", "branch_name": "fix/bug-branch"}
    params.result_callback = AsyncMock()

    with patch("subprocess.run") as mock_run:
        # Mock successful subprocess calls
        mock_run.return_value.stdout = "https://github.com/user/repo/pull/1"
        mock_run.return_value.returncode = 0

        result = await git_ops.execute_agent_git_modification(params)

        assert result["status"] == "success"
        assert result["pr_url"] == "https://github.com/user/repo/pull/1"

        # Verify calls
        assert mock_run.call_count == 5
        
        # 1. Checkout
        mock_run.assert_any_call(["git", "checkout", "-b", "fix/bug-branch"], check=True, capture_output=True, text=True)
        
        # 2. Gemini
        mock_run.assert_any_call(["gemini", "Fix bug"], check=True, capture_output=True, text=True)

        # 3. Commit (checking 'add' and 'commit' sequentially is harder with assert_any_call if order matters strictly, 
        # but for this verified step it ensures they were called)
        mock_run.assert_any_call(["git", "add", "."], check=True, capture_output=True, text=True)
        mock_run.assert_any_call(["git", "commit", "-m", "Apply Gemini changes for: Fix bug"], check=True, capture_output=True, text=True)
        
        # 4. PR
        mock_run.assert_any_call(["gh", "pr", "create", "--title", "Agent modification: fix/bug-branch", "--body", "Fix bug"], check=True, capture_output=True, text=True)

        # Verify callback
        params.result_callback.assert_called_with({"status": "success", "pr_url": "https://github.com/user/repo/pull/1"})

@pytest.mark.asyncio
async def test_execute_agent_git_modification_failure():
    params = MagicMock()
    params.arguments = {"prompt": "Fix bug", "branch_name": "fix/bug-branch"}
    params.result_callback = AsyncMock()

    with patch("subprocess.run") as mock_run:
        # Mock failure on git checkout
        mock_run.side_effect = subprocess.CalledProcessError(1, cmd=["git", "checkout"], stderr="Branch exists")

        result = await git_ops.execute_agent_git_modification(params)

        assert result["status"] == "error"
        assert "Command failed" in result["error"]
        assert "Branch exists" in result["error"]

        # Verify callback was called with error
        params.result_callback.assert_called_with({"status": "error", "error": "Command failed: ['git', 'checkout']. Output: Branch exists"})
