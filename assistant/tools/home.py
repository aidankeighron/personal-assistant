"""PC / room control. Everything goes through the whitelisted host agent on the PC."""

from __future__ import annotations

import re
import time

from . import ToolContext, tool


@tool(
    "Switch the room/display profile on the PC (e.g. movie = bed TV, racing = sim rig, desk = normal).",
    mode={"type": "string", "description": "Display profile name, e.g. desk, movie, racing, projector"},
)
async def set_display_mode(ctx: ToolContext, mode: str) -> dict:
    return await ctx.rt.host.display(mode.lower().strip())


@tool("Open a whitelisted application or game on the PC.", app={"type": "string", "description": "App name"})
async def launch_app(ctx: ToolContext, app: str) -> dict:
    return await ctx.rt.host.launch(app)


@tool("Close a whitelisted application on the PC.", app={"type": "string"})
async def close_app(ctx: ToolContext, app: str) -> dict:
    return await ctx.rt.host.close_app(app)


@tool("List the apps/games and display modes the PC allows.")
async def list_pc_apps(ctx: ToolContext) -> dict:
    return await ctx.rt.host.apps()


@tool("Get PC stats: CPU, RAM, GPU/VRAM use, idle time, foreground app.")
async def pc_stats(ctx: ToolContext) -> dict:
    stats = await ctx.rt.host.stats()
    stats["idle"] = await ctx.rt.host.idle()
    return stats


@tool("Unload the LLM from GPU memory right now (e.g. before gaming).")
async def free_gpu(ctx: ToolContext) -> dict:
    for alias in ("fast", "router", "heavy"):
        await ctx.rt.llm.unload(ctx.rt.settings.model(alias))
    return {"unloaded": True}


@tool(
    "Show something on the projector/wall display. `what` is 'brief' (morning HUD), 'off', a URL, "
    "or raw HTML you wrote for a custom screen.",
    what={"type": "string"},
    title={"type": "string", "description": "Short name for a custom screen"},
)
async def project(ctx: ToolContext, what: str, title: str = "custom") -> dict:
    s = ctx.rt.settings
    base = s["server"]["public_url"].rstrip("/")
    token = s["server"].get("api_token", "")
    w = what.strip()
    if w.lower() == "off":
        return await ctx.rt.host.projector(None)
    if w.lower() == "brief":
        url = f"{base}/hud?token={token}"
    elif re.match(r"https?://", w):
        url = w
    else:
        slug = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-") or "custom"
        d = s.data_dir / "hud"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{slug}.html").write_text(w, encoding="utf-8")
        url = f"{base}/hud/{slug}?token={token}&v={int(time.time())}"
    res = await ctx.rt.host.projector(url)
    return {"url": url.split("?")[0], **res}
