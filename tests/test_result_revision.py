"""Model-directed candidate revision cannot turn uncertainty into invented evidence."""
import base64
import io
import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic
from PIL import Image
from pydantic import ValidationError

from connected_gallery.agent_runtime.group_transport import decode_containers
from connected_gallery.agent_runtime.organizer import GroupRevision, ResultOrganizer
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import store
from test_result_groups import accepted, group


def revision():
    return {"items": [{"photo_id": "b", "reason": "선택한 대상과 같은 빨간색이 보입니다."}],
            "groups": [{**group(("b",)), "title": "빨간 대상", "reason": "사진에 빨간 대상이 보입니다."}],
            "omitted": [{"photo_id": "c", "verdict": "uncertain", "reason": "파란 모습에서 선택한 빨간 대상과의 직접 관계를 확인하기 어렵습니다."}]}


def response(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "id": "comparison", "type": "tool_call", "args": args}])


class RevisionGateway:
    """A deterministic test model explicitly makes every inclusion/omission decision."""
    def __init__(self, revised=None, *, mutation=None):
        self.revised = revision() if revised is None else revised
        self.calls, self.proposals, self.compared = 0, 0, []
        self.mutation = mutation

    async def invoke(self, messages, schemas):
        self.calls += 1
        name = schemas[0]["name"]
        if name == "submit_result_groups":
            self.proposals += 1
            return response(name, {"groups": [group()]})
        if name == "submit_result_revision":
            self.proposals += 1
            assert "independent_group_feedback" in json.dumps([m.content for m in messages])
            return response(name, self.revised)
        assert name == "submit_group_member_review"
        serialized = json.dumps([m.content for m in messages])
        assert "independent_group_feedback" not in serialized
        assert "independently_verified_candidate_evidence" not in serialized
        assert "omitted" not in serialized
        blocks = messages[1].content
        images = [b for b in blocks if b.get("type") == "image"]
        assert len(images) == 2
        pixels = []
        for block in images:
            with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as image:
                pixels.append(image.getpixel((50, 50)))
        assert pixels[0][0] > 200
        metadata = json.loads(blocks[-1]["text"])
        assert set(metadata) == {"source_hint", "proposed_group", "proposed_item_reason"}
        item_reason = metadata["proposed_item_reason"]
        self.compared.append({"round": self.proposals, "reason": item_reason, "pixel": pixels[1]})
        # First review explicitly finds an issue; second checks the current
        # displayed claim using actual source and retained candidate images.
        supported = self.proposals == 2 and pixels[1][0] > 200 and "동일 인물" not in item_reason
        if self.proposals == 2 and self.mutation:
            mutation, self.mutation = self.mutation, None
            mutation()
        return response(name, {"anchor_supported": True, "anchor_reason": "원본의 빨간 대상을 확인함",
                               "verdict": "supported" if supported else "uncertain",
                               "reason": "현재 설명의 색상이 실제로 보임" if supported else "현재 설명을 확실히 입증하지 못함"})


@pytest.mark.asyncio
async def test_model_can_explicitly_omit_and_rewrite_then_independently_verify_retained_items(store):
    payload = io.BytesIO()
    Image.new("RGB", (100, 100), "blue").save(payload, "JPEG")
    store.put_image("c", payload.getvalue())
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    gateway = RevisionGateway()
    original = accepted()
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "revision"), request, original)
    assert result["grouping_status"] == "ready" and result["complete"] is True
    assert result["items"] == revision()["items"] and result["groups"] == revision()["groups"]
    assert "omitted" not in result and original == accepted()
    assert gateway.calls == 5 and gateway.proposals == 2
    assert [r["round"] for r in gateway.compared] == [1, 1, 2]
    assert gateway.compared[-1]["reason"] == revision()["items"][0]["reason"]
    proposals = [json.loads(r["data"]) for r in store.rows("SELECT data FROM events WHERE kind='group_proposal' ORDER BY seq")]
    assert proposals[1]["omitted"] == revision()["omitted"]
    assert proposals[1]["accepted_photo_ids"] == ["b", "c"]
    checks = [json.loads(r["data"]) for r in store.rows("SELECT data FROM events WHERE kind='group_evidence_review' ORDER BY seq")]
    assert checks[1]["accepted_count"] == 2 and checks[1]["retained_count"] == checks[1]["omitted_count"] == 1
    assert checks[1]["supported"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda r: r["items"][0].update(photo_id="foreign"),
    lambda r: r["omitted"][0].update(photo_id="foreign"),
    lambda r: r["items"][0].update(photo_id="a"),
    lambda r: r.update(omitted=[]),
    lambda r: r["items"].append(dict(r["items"][0])),
    lambda r: r["omitted"].append(dict(r["omitted"][0])),
    lambda r: r["omitted"][0].update(photo_id="b"),
    lambda r: r["groups"][0].update(photo_ids=["b", "c"]),
    lambda r: r["groups"][0].update(photo_ids=["c"]),
])
async def test_revision_cannot_add_silently_drop_duplicate_or_group_an_omitted_candidate(store, mutate):
    revised = revision()
    mutate(revised)
    gateway = RevisionGateway(revised)
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "bad-revision"), request, accepted())
    assert result["grouping_status"] == "failed" and result["items"] == accepted()["items"]
    assert result["groups"] == [] and gateway.proposals == 2
    assert len(gateway.compared) == 2  # Invalid revision is rejected before final review.


@pytest.mark.asyncio
async def test_all_omitted_does_not_create_an_empty_ready_result_or_cache(store):
    revised = {"items": [], "groups": [], "omitted": [
        {"photo_id": pid, "verdict": "uncertain", "reason": "직접 관계를 확실히 검토하지 못함"} for pid in ("b", "c")]}
    gateway = RevisionGateway(revised)

    class Runner:
        async def execute(self, rid, request):
            return await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, rid), request, accepted())

    service = RunService(store, Runner())
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    run = service.start(RunRequest(role="explorer", explore=explore))
    await service.tasks[run["id"]]
    assert service.get(run["id"])["status"] == "incomplete"
    assert service.get(run["id"])["result"]["items"] == accepted()["items"]
    assert service.ready(explore)["state"] == "pending"
    assert not store.rows("SELECT key FROM cache")
    failure = json.loads(store.rows("SELECT data FROM events WHERE kind='grouping_failed'")[0]["data"])
    assert failure["code"] == "empty_revision" and len(gateway.compared) == 2


@pytest.mark.asyncio
async def test_a_modest_group_cannot_hide_an_unsupported_retained_item_reason(store):
    revised = revision()
    revised["items"][0]["reason"] = "이 사진에는 동일 인물이 보입니다."
    gateway = RevisionGateway(revised)
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "card-claim"), request, accepted())
    assert result["grouping_status"] == "failed" and result["items"] == accepted()["items"]
    assert gateway.proposals == 2 and gateway.calls == 5
    assert gateway.compared[-1]["reason"] == revised["items"][0]["reason"]


@pytest.mark.asyncio
async def test_supported_subset_does_not_upgrade_an_incomplete_retrieval(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await ResultOrganizer(RevisionGateway()).organize(
        GalleryTools(store, None, request, "partial-retrieval"), request, {**accepted(), "complete": False})
    assert result["grouping_status"] == "ready" and result["complete"] is False
    assert result["items"] == revision()["items"]


@pytest.mark.asyncio
async def test_deleting_an_omitted_photo_during_final_review_prevents_publication(store):
    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    gateway = RevisionGateway(mutation=lambda: store.delete("c"))
    with pytest.raises(ValueError):
        await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "changed-corpus"), request, accepted())
    assert not store.rows("SELECT key FROM cache")


@pytest.mark.parametrize("field", ["items", "omitted"])
def test_revision_reasons_cannot_be_blank(field):
    value = revision()
    value[field][0]["reason"] = "  "
    with pytest.raises(ValidationError):
        GroupRevision.model_validate(value)


def test_revision_container_decoding_preserves_explicit_membership_and_reasons():
    value = revision()
    encoded = {key: json.dumps(items) for key, items in value.items()}
    decoded = decode_containers(encoded, GroupRevision.model_json_schema())
    assert GroupRevision.model_validate(decoded).model_dump(mode="json") == value
    assert all(isinstance(v, str) for v in encoded.values())


@pytest.mark.asyncio
async def test_both_organizer_rounds_serialize_with_actual_anthropic_sdk_without_network(store, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("This is serialization only; no model request is allowed")

    monkeypatch.setattr("httpx.Client.send", no_network)
    monkeypatch.setattr("httpx.AsyncClient.send", no_network)
    model = ChatAnthropic(model="fixture-model", api_key="fixture-key",
                          base_url="https://example.invalid", max_tokens=4096, max_retries=0)
    # Reproduce the former exact SDK restriction without invoking a model.
    with pytest.raises(ValueError, match="non-consecutive system messages"):
        model._get_request_payload([SystemMessage(content="first"), HumanMessage(content="images"),
                                    SystemMessage(content="revision")])

    class SerializedGateway(RevisionGateway):
        payloads = []

        async def invoke(self, messages, schemas):
            bound = model.bind_tools(schemas, tool_choice=schemas[0]["name"])
            payload = model._get_request_payload(messages, **bound.kwargs)
            json.dumps(payload)  # No live credentials or calls are involved.
            assert payload["tool_choice"]["name"] == schemas[0]["name"]
            assert [message.type for message in messages].count("system") == 1
            assert messages[0].type == "system"
            self.payloads.append(payload)
            return await super().invoke(messages, schemas)

    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    gateway = SerializedGateway()
    result = await ResultOrganizer(gateway).organize(GalleryTools(store, None, request, "sdk-rounds"), request, accepted())
    assert result["grouping_status"] == "ready" and gateway.proposals == 2
    assert len(gateway.payloads) == 5
    revised = next(p for p in gateway.payloads if p["tool_choice"]["name"] == "submit_result_revision")
    assert "SECOND and FINAL" in json.dumps(revised["system"])
    assert "independent_group_feedback" in json.dumps(revised["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("message, expected", [
    ("Model unavailable (ValueError)", "ValueError"),
    ("Model unavailable (BadRequestError)", "BadRequestError"),
    ("Model unavailable (ValueError) TOKEN_AND_PRIVATE_REQUEST", None),
    ("Model unavailable (TOKEN/AND/PRIVATE_REQUEST)", None),
    ("TOKEN_AND_PRIVATE_REQUEST", None),
])
async def test_group_failure_preserves_only_the_controlled_proxy_error_classifier(store, message, expected):
    class Unavailable:
        async def invoke(self, *args):
            raise RuntimeError(message)

    request = RunRequest(role="explorer", explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    result = await ResultOrganizer(Unavailable()).organize(GalleryTools(store, None, request, "safe-diagnostic"), request, accepted())
    assert result["grouping_status"] == "failed"
    payload = store.rows("SELECT data FROM events WHERE kind='grouping_failed'")[0]["data"]
    assert "TOKEN_AND_PRIVATE_REQUEST" not in payload and "TOKEN/AND/PRIVATE_REQUEST" not in payload
    diagnostic = json.loads(payload)["diagnostic"]
    assert diagnostic == ({"error_type": "RuntimeError", "upstream_error_type": expected}
                          if expected else {"error_type": "RuntimeError"})


def test_group_error_status_is_bounded_and_provider_body_is_not_logged():
    class HttpError(Exception):
        status_code = 429

    error = HttpError("PRIVATE_BODY_AND_CREDENTIALS")
    assert ResultOrganizer._gateway_diagnostic(error) == {"error_type": "HttpError", "status_code": 429}
    error.status_code = 10000
    assert ResultOrganizer._gateway_diagnostic(error) == {"error_type": "HttpError"}
