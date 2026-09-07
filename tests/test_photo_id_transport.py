from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from connected_gallery.agent_runtime.photo_id_transport import PhotoIdTransport


def test_long_ids_round_trip_without_changing_images_call_identity_or_prose_substrings():
    pid = "990f4c28-67eb-4cd8-880a-21bb18e8a052_1000065316"
    transport = PhotoIdTransport([pid, "short"])
    image = {"type": "image", "source": {"data": pid}}
    original = HumanMessage(content=[{"type": "text", "text": f'{{"photo_id":"{pid}","other":"prefix{pid}"}}'}, image])
    message = transport.outbound([original])[0]
    assert pid not in message.content[0]["text"].split(',')[0]
    assert "prefix" + pid in message.content[0]["text"]
    assert message.content[1] == image and original.content[0]["text"].count(pid) == 2
    alias = transport.forward[pid]
    answer = AIMessage(content="", tool_calls=[{"name": "inspect_photos", "id": "call-1", "type": "tool_call", "args": {"photo_ids": [alias, "short"]}}])
    restored = transport.inbound(answer)
    assert restored.tool_calls[0]["args"]["photo_ids"] == [pid, "short"]
    assert restored.tool_calls[0]["id"] == "call-1"
    assert transport.outbound([restored])[0].tool_calls == answer.tool_calls
    assert transport.outbound([ToolMessage(content=pid,tool_call_id="call-1")])[0].tool_call_id == "call-1"


def test_aliases_never_shadow_actual_ids_and_unknown_aliases_are_not_resolved():
    pid = "a" * 40
    transport = PhotoIdTransport([pid, "__cg_photo_0000__"])
    assert set(transport.reverse).isdisjoint({pid, "__cg_photo_0000__"})
    response = AIMessage(content="", tool_calls=[{"name":"inspect_photos","id":"call","type":"tool_call","args":{"photo_ids":["__cg_photo_9999__"]}}])
    assert transport.inbound(response).tool_calls[0]["args"]["photo_ids"] == ["__cg_photo_9999__"]
