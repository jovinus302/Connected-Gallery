import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from connected_gallery.agent_runtime.group_transport import MAX_CONTAINER_JSON_LENGTH, container_shapes, decode_containers
from connected_gallery.agent_runtime.organizer import GroupProposal, ResultOrganizer
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import store
from test_result_groups import GroupGateway, accepted, group, prepared


def test_only_declared_containers_decode_without_changing_scalar_strings_or_members():
    value = group()
    value.update(title='["keep this exact title"]', reason='{"keep":"this exact reason"}', photo_ids=json.dumps(value["photo_ids"]))
    args = {"groups": json.dumps([value])}
    normalized = decode_containers(args, GroupProposal.model_json_schema())
    assert normalized == {"groups": [{**value, "photo_ids": ["b", "c"]}]}
    assert isinstance(args["groups"], str)  # No mutation of provider submission.
    result = GroupProposal.model_validate(normalized)
    assert result.groups[0].title == value["title"] and result.groups[0].reason == value["reason"]


@pytest.mark.parametrize("container", ["not JSON", "[", "null", "3", '{"g":[]}', {"g": []},
                                         '[{"photo_ids":[],"photo_ids":["b"]}]', '[NaN]'])
def test_malformed_or_wrong_container_is_not_replaced_with_empty_or_wrapped(container):
    args = {"groups": container}
    normalized = decode_containers(args, GroupProposal.model_json_schema())
    assert normalized == args
    with pytest.raises(ValidationError):
        GroupProposal.model_validate(normalized)


def test_over_budget_encoded_container_is_not_parsed():
    container = " " * MAX_CONTAINER_JSON_LENGTH + json.dumps([group()])
    args = {"groups": container}
    assert decode_containers(args, GroupProposal.model_json_schema()) == args
    with pytest.raises(ValidationError):
        GroupProposal.model_validate(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("members", [("b", "c"), ("b", "foreign"), ("b", "b")])
async def test_decoded_groups_still_require_exact_partition_and_independent_review(store, members):
    class EncodedGateway(GroupGateway):
        async def invoke(self, messages, schemas):
            reply = await super().invoke(messages, schemas)
            if schemas[0]["name"] == "submit_result_groups":
                value = group(members)
                value["photo_ids"] = json.dumps(value["photo_ids"])
                reply.tool_calls[0]["args"] = {"groups": json.dumps([value])}
            return reply

    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    gateway = EncodedGateway()
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "encoded-containers"), request, accepted())
    if members == ("b", "c"):
        assert result == prepared() and gateway.calls == 3
        assert len(store.rows("SELECT seq FROM events WHERE kind='group_member_review'")) == 2
    else:
        assert result["grouping_status"] == "failed" and result["items"] == accepted()["items"]
        assert not store.rows("SELECT seq FROM events WHERE kind='group_member_review'")


@pytest.mark.asyncio
async def test_format_repair_has_specific_paths_and_shapes_without_raw_response_text():
    class Gateway:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls == 1:
                args = {"groups": {"private": "SENSITIVE_RAW_VALUE"}}
            else:
                repair = messages[-1].content
                details = json.loads(repair[repair.index("{"):])
                assert details["validation_issues"] == [{"path": ["groups"], "type": "list_type"}]
                assert "list_type" in repair and "actual_type" in repair and "dict" in repair
                assert "SENSITIVE_RAW_VALUE" not in repair and "private" not in repair
                args = {"groups": [group()]}
            return AIMessage(content="", tool_calls=[{"name": "submit_result_groups", "id": "r", "args": args, "type": "tool_call"}])

    gateway = Gateway()
    result = await ResultOrganizer(gateway)._submit([HumanMessage(content="actual images omitted in fake test")], GroupProposal, "submit_result_groups")
    assert result.groups[0].photo_ids == ["b", "c"] and gateway.calls == 2


def test_container_diagnostics_never_include_string_contents_or_unknown_keys():
    shapes = container_shapes({"groups": "SECRET_ENCODED_GROUPS", "PRIVATE_FIELD": "SECRET"}, GroupProposal.model_json_schema())
    assert shapes == [{"path": [], "expected": "object", "actual_type": "dict", "length": 2},
                      {"path": ["groups"], "expected": "array", "actual_type": "str", "length": 21}]
    assert "SECRET" not in json.dumps(shapes) and "PRIVATE_FIELD" not in json.dumps(shapes)
