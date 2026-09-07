"""Offline revisions observe images, isolate diagnostics and replace only their source row."""
import asyncio
import base64
import copy
import io
import json
import sqlite3

import pytest
from langchain_core.messages import AIMessage
from PIL import Image

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.agent_runtime.prepared_revision import PreparedRevisionRunner
from connected_gallery.application.prepared_revision import SOURCE_EVENT, REVIEW_EVENT, image_fingerprints, source_event, text_sha256
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import Box, ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import asset, store
from test_result_groups import prepared


OLD = "OLD_UNTRUSTED_CLAIM_MARKER"
DIAGNOSTIC = "PROPOSER_ONLY_DIAGNOSTIC_MARKER"


def selection():
    return ExploreInput(anchor=SemanticAnchor(photo_id="a", box=Box(x=.1, y=.2, width=.4, height=.3),
                                              label="선택한 빨간 대상"))


def revised():
    return {"label": "보이는 빨간 대상의 연결", "items": [{"photo_id":"b", "reason":"사진에 빨간 대상이 보입니다."}],
            "groups":[{"id":"neutral", "title":"빨간 대상", "reason":"선택 부분과 빨간색이 공통입니다.", "photo_ids":["b"]}],
            "omitted":[{"photo_id":"c", "verdict":"uncertain", "reason":"선택 부분과의 직접 관계를 충분히 설명하지 못했습니다."}]}


def response(name, args):
    return AIMessage(content="", tool_calls=[{"name":name, "id":"fixture", "type":"tool_call", "args":args}])


class Gateway:
    def __init__(self, proposal=None, *, verdict="supported", mutation=None, repair_label=False):
        self.proposal = revised() if proposal is None else proposal
        self.verdict, self.mutation, self.repair_label = verdict, mutation, repair_label
        self.calls, self.proposals, self.reviews = 0, 0, []

    async def invoke(self, messages, schemas):
        self.calls += 1
        name = schemas[0]["name"]
        content = json.dumps([message.content for message in messages], ensure_ascii=False)
        assert [message.type for message in messages].count("system") == 1
        images = [b for b in messages[1].content if isinstance(b, dict) and b.get("type") == "image"]
        shapes = []
        for block in images:
            with Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))) as image:
                shapes.append(image.size)
        if name == "submit_result_revision":
            self.proposals += 1
            assert "untrusted_prepared_draft" in content and OLD in content and DIAGNOSTIC in content
            assert "independently_verified_candidate_evidence" not in content
            assert shapes == [(40, 30), (100, 100), (100, 100), (40, 30)]
            if self.proposals > 1:
                assert "independent_group_feedback" in content
            proposed = copy.deepcopy(self.proposal)
            if self.repair_label and self.proposals == 1:
                proposed["label"] = "UNSUPPORTED_LABEL"
            if self.mutation:
                mutation, self.mutation = self.mutation, None
                mutation()
            return response(name, proposed)
        assert name == "submit_group_member_review"
        assert DIAGNOSTIC not in content and OLD not in content
        assert "untrusted_prepared_draft" not in content and "independent_group_feedback" not in content
        assert "omitted" not in content
        assert shapes == [(40, 30), (100, 100)]
        metadata = json.loads(messages[1].content[-1]["text"])
        assert set(metadata) == {"source_hint", "proposed_group", "proposed_item_reason", "proposed_result_label"}
        self.reviews.append(metadata)
        verdict = "uncertain" if metadata["proposed_result_label"] == "UNSUPPORTED_LABEL" else self.verdict
        return response(name, {"anchor_supported":True, "anchor_reason":"원본에서 빨간 부분이 보입니다.",
                               "verdict":verdict, "reason":"직접 보이는 범위에서 문구를 비교했습니다."})


def setup_service(store, gateway=None):
    gateway = gateway or Gateway()
    service = RunService(store, PreparedRevisionRunner(store, ResultOrganizer(gateway)))
    query = selection()
    request = RunRequest(role="explorer", explore=query)
    key = service.cache_key(request)
    original = prepared()
    original.update(label=OLD)
    for item in original["items"]:
        item["reason"] = OLD
    for group in original["groups"]:
        group.update(title=OLD, reason=OLD)
    raw = json.dumps(original, ensure_ascii=False, indent=3)
    store.write("INSERT INTO cache VALUES(?,?,?)", (key, store.revision, raw))
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("old", "old", request.model_dump_json(), "completed", raw, None, 1))
    return service, query, key, raw, gateway


async def run_revision(service, query, **kwargs):
    created = service.start_prepared_revision(query, feedback=DIAGNOSTIC, **kwargs)
    rid = created["id"]
    task = service.tasks.get(rid)
    if task:
        await task
    return service.get(rid)


@pytest.mark.asyncio
async def test_actual_images_fresh_reviewer_first_round_rewrites_label_items_groups_and_model_omission(store):
    service, query, key, raw, gateway = setup_service(store)
    revision = store.revision
    old_run = store.rows("SELECT * FROM runs WHERE id='old'")[0]
    result = await run_revision(service, query, feedback_source="sha256:" + text_sha256(DIAGNOSTIC),
                                expected_cache_sha256=text_sha256(raw), expected_revision=revision)
    assert result["status"] == "completed" and gateway.proposals == 1 and len(gateway.reviews) == 1
    value = result["result"]
    assert value["label"] == revised()["label"] and value["items"] == revised()["items"]
    assert value["groups"] == revised()["groups"] and "omitted" not in value
    assert service.prepared_cache_key(query) == key and service.ready(query)["result"] == value
    assert store.revision == revision and store.rows("SELECT * FROM runs WHERE id='old'")[0] == old_run
    source = source_event(store, result["id"])
    assert source["original_cache_data"] == raw and source["original_cache_sha256"] == text_sha256(raw)
    assert source["original_cache_key"] == key and source["prior_matching_run_ids"] == ["old"]
    assert set(source["image_fingerprints"]) == {"source_crop", "candidate:b", "candidate:c"}
    assert source["untrusted_quality_feedback"] == DIAGNOSTIC
    assert store.rows("SELECT 1 FROM events WHERE kind=?", (REVIEW_EVENT,))
    assert not store.rows("SELECT 1 FROM events WHERE kind='tool'")
    assert store.rows("SELECT count(*) AS n FROM cache")[0]["n"] == 1


@pytest.mark.asyncio
async def test_result_label_is_independently_checked_and_model_can_repair_it(store):
    service, query, key, raw, gateway = setup_service(store, Gateway(repair_label=True))
    result = await run_revision(service, query)
    assert result["status"] == "completed" and gateway.proposals == 2
    assert [r["proposed_result_label"] for r in gateway.reviews] == ["UNSUPPORTED_LABEL", revised()["label"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda p: p["items"][0].update(photo_id="new"),
    lambda p: p["items"][0].update(photo_id="a"),
    lambda p: p.update(omitted=[]),
    lambda p: p["items"].append(dict(p["items"][0])),
    lambda p: p["groups"][0].update(photo_ids=["c"]),
    lambda p: p.update(items=[], groups=[], omitted=[{"photo_id":pid,"verdict":"uncertain","reason":"근거 부족"} for pid in ["b","c"]]),
    lambda p: p.update(label=" "),
])
async def test_invalid_revision_cannot_replace_current_cache_or_manufacture_empty(store, mutate):
    proposal = revised()
    mutate(proposal)
    service, query, key, raw, gateway = setup_service(store, Gateway(proposal))
    result = await run_revision(service, query)
    assert result["status"] == "incomplete"
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw
    assert not store.rows("SELECT 1 FROM events WHERE kind=?", (REVIEW_EVENT,))


@pytest.mark.asyncio
async def test_failed_independent_review_keeps_old_bytes_and_does_not_claim_manual_qa_complete(store):
    service, query, key, raw, gateway = setup_service(store, Gateway(verdict="uncertain"))
    result = await run_revision(service, query)
    assert result["status"] == "incomplete" and gateway.proposals == 2
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw
    assert json.loads(store.rows("SELECT data FROM events WHERE kind='prepared_revision_incomplete'")[0]["data"])["cache_replaced"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cache", "version", "image", "model"])
async def test_concurrent_changes_cannot_be_overwritten_at_same_revision(store, monkeypatch, kind):
    service, query, key, raw, gateway = setup_service(store)
    changed_raw = raw + "\n"
    def mutation():
        if kind == "cache":
            # A genuinely separate SQLite connection models another prep worker.
            other = sqlite3.connect(store.root / "gallery.sqlite")
            with other:
                other.execute("UPDATE cache SET data=? WHERE key=?", (changed_raw, key))
            other.close()
        elif kind == "version":
            photo = store.photo("b").model_copy(update={"version":"2"})
            store.write("UPDATE photos SET version=?,data=? WHERE id='b'", ("2", photo.model_dump_json()))
        elif kind == "image":
            Image.new("RGB", (100,100), "blue").save(store.image_path("b"))
        else:
            monkeypatch.setenv("CG_MODEL", "different-profile")
    gateway.mutation = mutation
    result = await run_revision(service, query)
    assert result["status"] in ("failed", "incomplete")
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == (changed_raw if kind == "cache" else raw)
    assert not store.rows("SELECT 1 FROM events WHERE kind='prepared_revision_committed'")


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"expected_cache_sha256":"0"*64}, {"expected_revision":999}, {"feedback_source":"x"*241}])
async def test_stale_preflight_does_not_create_run_or_invoke_model(store, options):
    service, query, key, raw, gateway = setup_service(store)
    changes = store.db.total_changes
    with pytest.raises(ValueError):
        service.start_prepared_revision(query, feedback=DIAGNOSTIC, **options)
    assert store.db.total_changes == changes and gateway.calls == 0 and not service.tasks


@pytest.mark.asyncio
async def test_current_ordinary_start_remains_cache_hit_and_never_triggers_revision(store):
    service, query, key, raw, gateway = setup_service(store)
    hit = service.start(RunRequest(role="explorer", explore=query))
    assert hit["status"] == "completed" and gateway.calls == 0
    assert not store.rows("SELECT 1 FROM events WHERE kind=?", (SOURCE_EVENT,))


@pytest.mark.asyncio
async def test_interrupted_offline_run_never_recovers_as_normal_retrieval(store):
    service, query, key, raw, gateway = setup_service(store)
    service.schedule = lambda *args: None
    created = service.start_prepared_revision(query, feedback=DIAGNOSTIC)
    await service.recover()
    assert service.get(created["id"])["status"] == "incomplete" and gateway.calls == 0
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw


@pytest.mark.asyncio
async def test_forged_ready_return_without_independent_provenance_cannot_publish(store):
    service, query, key, raw, gateway = setup_service(store)
    class ForgedRunner:
        supports_prepared_revision = True
        async def execute(self, *args):
            return {**prepared(), "label":"FORGED"}
    service.runner = ForgedRunner()
    result = await run_revision(service, query)
    assert result["status"] == "failed"
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw


@pytest.mark.asyncio
async def test_model_transport_failure_preserves_original_bytes_and_records_failure(store):
    class Unavailable(Gateway):
        async def invoke(self, *args):
            raise RuntimeError("fixture transport unavailable")
    service, query, key, raw, gateway = setup_service(store, Unavailable())
    result = await run_revision(service, query)
    assert result["status"] == "incomplete"
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw


@pytest.mark.asyncio
async def test_image_is_required_before_a_new_run_is_created(store):
    service, query, key, raw, gateway = setup_service(store)
    store.image_path("b").unlink()
    changes = store.db.total_changes
    with pytest.raises(FileNotFoundError):
        service.start_prepared_revision(query, feedback=DIAGNOSTIC)
    assert store.db.total_changes == changes and gateway.calls == 0


@pytest.mark.asyncio
async def test_cache_replacement_and_run_completion_rollback_together(store, monkeypatch):
    service, query, key, raw, gateway = setup_service(store)
    # Fail the final event write after both UPDATEs; the transaction must undo them.
    store.write("CREATE TRIGGER fail_publish BEFORE INSERT ON events WHEN NEW.kind='prepared_revision_committed' BEGIN SELECT RAISE(ABORT,'fixture rollback'); END")
    result = await run_revision(service, query)
    assert result["status"] == "failed"
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw


def test_evidence_keys_do_not_collide_with_legal_photo_ids(store):
    store.upsert(asset("source_crop"))
    image = io.BytesIO()
    Image.new("RGB", (100,100), "blue").save(image, "JPEG")
    store.put_image("source_crop", image.getvalue())
    request = RunRequest(role="explorer", explore=selection())
    fingerprints = image_fingerprints(store, request, {"items":[{"photo_id":"source_crop"}]})
    assert set(fingerprints) == {"source_crop", "candidate:source_crop"}
    assert len(set(fingerprints.values())) == 2


@pytest.mark.asyncio
async def test_changed_region_label_is_not_silently_canonicalized_into_new_source(store):
    service, query, key, raw, gateway = setup_service(store)
    region = {"id":"current_region", "photo_id":"a", "box":query.anchor.box.model_dump(),
              "kind":"object", "label":query.anchor.label, "evidence":"fixture"}
    store.write("INSERT INTO analyses VALUES(?,?)", ("a", encoded({"photo_id":"a","description":"fixture","regions":[region]})))
    query = query.model_copy(update={"anchor":query.anchor.model_copy(update={"region_id":region["id"]})})
    key = service.cache_key(RunRequest(role="explorer", explore=query))
    store.write("INSERT INTO cache VALUES(?,?,?)", (key, store.revision, raw))
    def mutation():
        analysis = store.analysis("a")
        analysis["regions"][0]["label"] = "다른 선택 의미"
        store.write("UPDATE analyses SET data=? WHERE photo_id='a'", (encoded(analysis),))
    gateway.mutation = mutation
    result = await run_revision(service, query)
    assert result["status"] in ("failed", "incomplete")
    assert store.rows("SELECT data FROM cache WHERE key=?", (key,))[0]["data"] == raw
    assert not store.rows("SELECT 1 FROM events WHERE kind='prepared_revision_committed'")
