"""Opt-in synthetic image + real tool round-trip. Never reads personal Gallery images."""

import asyncio
import base64
import io
from dotenv import load_dotenv
from PIL import Image
from langchain_core.messages import HumanMessage, ToolMessage
from connected_gallery.adapters.proxy import ProxyGateway


async def main():
    load_dotenv()
    im = Image.new("RGB", (128, 64), "red")
    im.paste("blue", (64, 0, 128, 64))
    b = io.BytesIO()
    im.save(b, "PNG")
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": "Call report_colors with the left and right colors of this synthetic image.",
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(b.getvalue()).decode(),
                    },
                },
            ]
        )
    ]
    schema = {
        "name": "report_colors",
        "description": "Report observed colors",
        "input_schema": {
            "type": "object",
            "properties": {"left": {"type": "string"}, "right": {"type": "string"}},
            "required": ["left", "right"],
        },
    }
    gateway = ProxyGateway()
    reply = await gateway.invoke(messages, [schema])
    assert reply.tool_calls, "No tool call"
    args = reply.tool_calls[0]["args"]
    assert args["left"].lower() == "red" and args["right"].lower() == "blue", args
    messages += [
        reply,
        ToolMessage(content="Saved. Reply OK.", tool_call_id=reply.tool_calls[0]["id"]),
    ]
    await gateway.invoke(messages, [schema])
    print("PASS: synthetic image understanding and tool-result round-trip")


asyncio.run(main())
