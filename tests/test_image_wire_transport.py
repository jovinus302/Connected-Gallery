"""Exercise the installed SDK's serialized request, without opening a socket."""
import base64
import copy
import io
import json

import httpx2
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from PIL import Image

from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.adapters.store import Store
from connected_gallery.agent_runtime.photo_id_transport import PhotoIdTransport
from connected_gallery.domain.models import PhotoAsset, RunRequest
from connected_gallery.gallery_tools.registry import GalleryTools


PHOTO_IDS = [f"synthetic-photo-with-long-opaque-identifier-{i}" for i in range(3)]


@pytest.fixture
def image_tools(tmp_path):
    store = Store(tmp_path)
    for i, pid in enumerate(PHOTO_IDS):
        width, height = 240 + i * 16, 160 + i * 8
        store.upsert(PhotoAsset(id=pid, device_id="fixture", version="1",
                                width=width, height=height))
        output = io.BytesIO()
        color = [0, 0, 0]
        color[i] = 255
        Image.new("RGB", (width, height), tuple(color)).save(output, "JPEG")
        store.put_image(pid, output.getvalue())
    yield GalleryTools(store, None, RunRequest(role="context", photo_ids=[PHOTO_IDS[0]]), "wire-test")
    store.close()


def schema_for_members():
    return [{"name": "submit_photo_context", "description": "Submit inspected members",
             "input_schema": {"type": "object", "properties": {
                 "photo_ids": {"type": "array", "items": {"type": "string", "enum": PHOTO_IDS[1:]}}
             }, "required": ["photo_ids"]}}]


def test_schema_enums_use_message_aliases_without_mutating_original():
    transport = PhotoIdTransport(PHOTO_IDS)
    schemas = schema_for_members()
    original = copy.deepcopy(schemas)
    outbound = transport.outbound_schemas(schemas)
    allowed = outbound[0]["input_schema"]["properties"]["photo_ids"]["items"]["enum"]
    assert allowed == [transport.forward[pid] for pid in PHOTO_IDS[1:]]
    assert schemas == original
    response = AIMessage(content="", tool_calls=[{
        "name": "submit_photo_context", "id": "submit-1", "type": "tool_call",
        "args": {"photo_ids": allowed},
    }])
    assert transport.inbound(response).tool_calls[0]["args"]["photo_ids"] == PHOTO_IDS[1:]


@pytest.mark.asyncio
@pytest.mark.parametrize("placement", ["tool_result", "reviewer_message"])
async def test_sdk_wire_preserves_image_bytes_photo_pairs_and_enum_aliases(
        monkeypatch, image_tools, placement):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://fixture.invalid")
    transport = PhotoIdTransport(PHOTO_IDS)
    original_blocks = {pid: image_tools.image_block(pid) for pid in PHOTO_IDS}
    if placement == "tool_result":
        messages = [HumanMessage(content=original_blocks[PHOTO_IDS[0]]),
                    AIMessage(content="", tool_calls=[{
                        "name": "inspect_photos", "id": "inspect-1", "type": "tool_call",
                        "args": {"photo_ids": PHOTO_IDS[1:]},
                    }]),
                    ToolMessage(content=sum((original_blocks[pid] for pid in PHOTO_IDS[1:]), []),
                                tool_call_id="inspect-1")]
    else:
        # Reviews remove old captions and retain an explicit ID immediately
        # before each image. Sorting candidates must keep these pairs together.
        content = []
        for pid in [PHOTO_IDS[0], *sorted(PHOTO_IDS[1:], reverse=True)]:
            content += [{"type": "text", "text": json.dumps({"photo_id": pid, "source": pid == PHOTO_IDS[0]})},
                        original_blocks[pid][1]]
        messages = [HumanMessage(content=content)]
    captured = []

    def handle(request):
        assert request.url.host == "fixture.invalid"
        assert request.url.path == "/v1/messages"
        body = json.loads(request.content)
        captured.append(body)
        members = body["tools"][0]["input_schema"]["properties"]["photo_ids"]["items"]["enum"]
        return httpx2.Response(200, json={
            "id": "fixture-response", "type": "message", "role": "assistant", "model": "fixture-model",
            "content": [{"type": "tool_use", "id": "submit-1", "name": "submit_photo_context",
                         "input": {"photo_ids": members}}],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle), trust_env=False) as client:
        monkeypatch.setattr("langchain_anthropic.chat_models._get_default_async_httpx_client",
                            lambda **kwargs: client)
        response = await ProxyGateway(primary="fixture-model", fallback=None, repeat_primary=False).invoke(
            transport.outbound(messages), transport.outbound_schemas(schema_for_members()))
    assert len(captured) == 1
    wire = captured[0]
    assert wire["tool_choice"] == {"type": "tool", "name": "submit_photo_context"}
    expected_members = [transport.forward[pid] for pid in PHOTO_IDS[1:]]
    assert wire["tools"][0]["input_schema"]["properties"]["photo_ids"]["items"]["enum"] == expected_members

    pairs = []
    for message in wire["messages"]:
        if message["role"] != "user":
            continue
        blocks = message["content"]
        if placement == "tool_result" and blocks[0]["type"] == "tool_result":
            assert blocks[0]["tool_use_id"] == "inspect-1"
            blocks = blocks[0]["content"]
        assert len(blocks) % 2 == 0
        for i in range(0, len(blocks), 2):
            pairs.append((json.loads(blocks[i]["text"])["photo_id"], blocks[i + 1]))
    assert len(pairs) == 3
    assert len({pid for pid, _ in pairs}) == 3
    for alias, block in pairs:
        pid = transport.reverse[alias]
        assert block == original_blocks[pid][1]
        decoded = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
        index = PHOTO_IDS.index(pid)
        assert decoded.size == (240 + index * 16, 160 + index * 8)
        pixel = decoded.getpixel((0, 0))
        assert pixel[index] > 250
        assert all(pixel[channel] < 5 for channel in range(3) if channel != index)
    assert transport.inbound(response).tool_calls[0]["args"]["photo_ids"] == PHOTO_IDS[1:]
    assert all(pid not in json.dumps(wire) for pid in PHOTO_IDS)
