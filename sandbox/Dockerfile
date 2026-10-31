# The agents' sandbox: bash, git, python, node and Claude Code.
# Used two ways:
#   - a long-lived container `pa-sandbox` for the sandbox_shell tool
#   - throwaway `docker run` containers for each Jarvis Claude Code run
# Build on M7:  docker build -t pa-sandbox:latest sandbox/
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates python3 python3-pip python3-venv build-essential ripgrep jq less \
        openssh-client sqlite3 unzip procps \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# Containers run with --user <assistant uid> and HOME=/home/agent mounted from the vault,
# so the Claude login persists and files they write are owned by the assistant service user.
RUN mkdir -p /work /home/agent && chmod 777 /work /home/agent
ENV HOME=/home/agent
WORKDIR /work
CMD ["sleep", "infinity"]
