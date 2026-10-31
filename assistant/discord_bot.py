"""Optional Discord bridge: DM the bot (or @mention it) and it relays to the assistant.

Setup: create a bot at https://discord.com/developers, enable the Message Content intent,
put DISCORD_TOKEN and DISCORD_USER_ID (your numeric user id) in .env, then:
    pip install -e ".[discord]"
    python -m assistant.discord_bot
Only messages from DISCORD_USER_ID are answered.
"""

from __future__ import annotations

import os

from .orchestrator import Orchestrator
from .runtime import Runtime


def main() -> None:
    import discord

    rt = Runtime.create()
    orch = Orchestrator(rt)
    owner = int(os.environ["DISCORD_USER_ID"])
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_message(msg: discord.Message) -> None:
        if msg.author.bot or msg.author.id != owner:
            return
        is_dm = isinstance(msg.channel, discord.DMChannel)
        if not is_dm and client.user not in msg.mentions:
            return
        text = msg.content.replace(f"<@{client.user.id}>", "").strip()
        async with msg.channel.typing():
            res = await orch.handle(text, conversation=f"discord-{msg.channel.id}", source="discord")
        await msg.reply(f"**{res['agent'].title()}:** {res['text']}"[:1990])

    client.run(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    main()
