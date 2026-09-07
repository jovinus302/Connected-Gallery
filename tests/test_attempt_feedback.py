"""Prior failures guide new proposals without becoming current visual evidence."""
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_runtime.organizer import ResultOrganizer
from connected_gallery.agent_runtime.reviewer import EvidenceReviewer
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION, RETRIEVAL_POLICY
from connected_gallery.application.attempt_feedback import (
    IDENTITY_EVENT, RETRY_FEEDBACK_VERSION, execution_identity,
    load_prior_attempt_feedback, record_execution_identity,
)
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import Box, ExploreInput, ExplorationResult, RunRequest, SemanticAnchor
from connected_gallery.domain.empty_evidence import EMPTY_EVIDENCE_SPEC, EMPTY_EVIDENCE_POLICY
from connected_gallery.gallery_tools.registry import GalleryTools
from test_contracts import asset, store
from test_result_groups import group
from test_result_revision import RevisionGateway, response
from test_reviewer import RetrievalGateway
from test_demo_profile_scripts import script


MARKER = "PRIOR_UNTRUSTED_MARKER"


def request(**changes):
    return RunRequest(role="explorer", explore=ExploreInput(
        **{"anchor": SemanticAnchor(photo_id="a"), **changes}))


def history():
    decisions = [{"photo_id": pid, "verdict": "supported", "reason": MARKER} for pid in ("b", "c")]
    return [
        ("evidence_review", {"candidate_count": 2, "accepted_count": 2, "anchor_supported": True,
                             "selected_meanings": ["selected crop"], "decisions": decisions}),
        ("group_proposal", {"attempt": 1, "groups": [group()], "accepted_photo_ids": ["b", "c"],
                            "retained_items": [{"photo_id": pid, "reason": MARKER} for pid in ("b", "c")], "omitted": []}),
        ("group_evidence_review", {"attempt": 1, "group_count": 1, "accepted_count": 2,
                                   "retained_count": 2, "omitted_count": 0, "anchor_supported": True,
                                   "valid_members": True, "supported": False, "member_reviews": [
                                       {"group_index": 0, "group_id": "g", "photo_id": pid,
                                        "anchor_supported": True, "anchor_reason": "visible source",
                                        "verdict": "uncertain", "reason": MARKER} for pid in ("b", "c")]}),
        ("grouping_failed", {"code": "unsupported_group_claims", "stage": "review",
                             "message": "PRIVATE_PROVIDER_BODY", "diagnostic": {"raw_body": "PRIVATE_PROVIDER_BODY"}}),
    ]


def empty_history(store):
    return [("empty_evidence_review", {
        "spec": EMPTY_EVIDENCE_SPEC, "policy": EMPTY_EVIDENCE_POLICY, "status": "needs_investigation",
        "gallery_revision": store.revision, "source_photo_id": "a", "eligible_count": 2,
        "inspected_photo_ids": ["a", "b", "c"], "photo_versions": {p.id: p.version for p in store.photos()},
        "selected_meaning": "selected crop", "anchor_supported": True, "scope_sufficient": True,
        "scope_reason": "The old empty conclusion needs further investigation",
        "decisions": [{"photo_id": "b", "verdict": "possible_relation", "reason": MARKER},
                      {"photo_id": "c", "verdict": "uncertain", "reason": "Image comparison needs fresh observation"}],
        "raw_provider_response": "PRIVATE_PROVIDER_BODY", "nested_history": {"untrusted": "PRIVATE_PROVIDER_BODY"},
    })]


def attempt(store, rid, req=None, *, status="incomplete", identity=True, events=None):
    req = req or request()
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        rid, rid, req.model_dump_json(), "running", None, None, 0))
    if identity:
        record_execution_identity(store, rid, req)
    for kind, data in history() if events is None else events:
        store.event(rid, kind, data)
    store.write("UPDATE runs SET status=? WHERE id=?", (status, rid))
    if status in ("failed", "incomplete", "completed", "cancelled"):
        store.event(rid, "finished", {"status": status})
    return req


def fresh(store, req=None, rid="current", *, identity=True):
    req = req or request()
    attempt(store, rid, req, status="running", identity=identity, events=[])
    return GalleryTools(store, None, req, rid)


def change_event(store, rid, kind, mutate):
    row = store.rows("SELECT seq,data FROM events WHERE run_id=? AND kind=?", (rid, kind))[0]
    data = json.loads(row["data"])
    mutate(data)
    store.write("UPDATE events SET data=? WHERE seq=?", (encoded(data), row["seq"]))


def test_exact_snapshot_reads_only_last_terminal_failure_without_mutating_store_or_evidence(store):
    attempt(store, "earlier")
    attempt(store, "latest", status="failed")
    attempt(store, "active", status="running")
    attempt(store, "completed", status="completed")
    attempt(store, "cancelled", status="cancelled")
    toolkit = fresh(store)
    changes = store.db.total_changes
    initial_versions = dict(toolkit.versions)
    prior = load_prior_attempt_feedback(toolkit)
    assert prior["prior_run_id"] == "latest" and prior["terminal_status"] == "failed"
    assert prior["version"] == RETRY_FEEDBACK_VERSION
    assert MARKER in encoded(prior) and "PRIVATE_PROVIDER_BODY" not in encoded(prior)
    assert store.db.total_changes == changes
    assert not toolkit.seen and not toolkit.covered and not toolkit.searched
    assert toolkit.result is None and toolkit.versions == initial_versions
    assert not store.rows("SELECT * FROM cache")


def test_empty_review_failure_becomes_only_bounded_leads_without_old_observation_credit(store):
    attempt(store, "empty-previous", status="failed", events=empty_history(store))
    toolkit = fresh(store)
    before = store.db.total_changes
    prior = load_prior_attempt_feedback(toolkit)
    assert prior["prior_run_id"] == "empty-previous"
    event = prior["events"][0]
    assert event["kind"] == "empty_evidence_review" and event["data"]["status"] == "needs_investigation"
    assert [lead["verdict"] for lead in event["data"]["candidate_leads"]] == ["possible_relation", "uncertain"]
    assert {lead["photo_id"] for lead in event["data"]["candidate_leads"]} == {"b", "c"}
    for removed in ("inspected_photo_ids", "photo_versions", "empty_evidence", "accepted_photo_ids", "PRIVATE_PROVIDER_BODY"):
        assert removed not in encoded(event["data"])
    assert store.db.total_changes == before and not toolkit.seen and not toolkit.covered and not toolkit.searched
    assert toolkit.result is None and not store.rows("SELECT * FROM cache")
    with pytest.raises(ValueError, match="Inspect anchor|Inspect candidate"):
        toolkit.submit_exploration_result(ExplorationResult(label="lead only", items=[{"photo_id": "b", "reason": MARKER}]))


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(spec=999),
    lambda d: d.update(policy="obsolete-negative-policy"),
    lambda d: d.update(gallery_revision=0),
    lambda d: d.update(source_photo_id="b"),
    lambda d: d.update(eligible_count=1),
    lambda d: d["inspected_photo_ids"].pop(),
    lambda d: d["inspected_photo_ids"].append("b"),
    lambda d: d["photo_versions"].update(b="old-version"),
    lambda d: d["photo_versions"].pop("c"),
    lambda d: d["decisions"][0].update(photo_id="foreign"),
    lambda d: d["decisions"][0].update(photo_id="a"),
    lambda d: d["decisions"][0].update(photo_id="c"),
    lambda d: d["decisions"][0].update(verdict="supported"),
    lambda d: d.update(anchor_supported="true"),
    lambda d: d.update(scope_reason="x" * 1201),
    lambda d: [item.update(verdict="unrelated") for item in d["decisions"]],
    lambda d: d.update(status="verified_empty"),
])
def test_old_empty_review_must_match_entire_exact_snapshot_and_failed_verdict(store, mutate):
    attempt(store, "older", events=empty_history(store))
    attempt(store, "latest", events=empty_history(store))
    change_event(store, "latest", "empty_evidence_review", mutate)
    assert load_prior_attempt_feedback(fresh(store)) is None


def test_empty_review_unrelated_members_are_not_forwarded_as_exclusion_instructions(store):
    events = empty_history(store)
    events[0][1]["decisions"][1]["verdict"] = "unrelated"
    attempt(store, "previous", events=events)
    prior = load_prior_attempt_feedback(fresh(store))
    assert [row["photo_id"] for row in prior["events"][0]["data"]["candidate_leads"]] == ["b"]
    assert "unrelated" not in encoded(prior)


def test_empty_review_unavailable_is_only_failure_metadata_without_semantic_claims(store):
    attempt(store, "previous", events=[("empty_evidence_review", {
        "spec": EMPTY_EVIDENCE_SPEC, "status": "insufficient", "code": "review_unavailable", "eligible_count": 2,
        "error": "PRIVATE_PROVIDER_BODY", "seconds": 45, "decisions": [{"photo_id": "b", "verdict": "possible_relation"}],
    })])
    prior = load_prior_attempt_feedback(fresh(store))
    assert prior["events"][0]["data"] == {
        "spec": EMPTY_EVIDENCE_SPEC, "status": "insufficient", "code": "review_unavailable", "eligible_count": 2}
    assert "PRIVATE_PROVIDER_BODY" not in encoded(prior) and "candidate_leads" not in encoded(prior)


def test_empty_candidate_budget_failure_is_validated_against_actual_eligible_count(store):
    for index in range(23):
        store.upsert(asset(f"extra-{index:02}"))
    attempt(store, "previous", events=[("empty_evidence_review", {
        "spec": EMPTY_EVIDENCE_SPEC, "status": "insufficient", "code": "candidate_budget",
        "eligible_count": 25, "candidate_budget": 24,
    })])
    toolkit = fresh(store)
    prior = load_prior_attempt_feedback(toolkit)
    assert prior["events"][0]["data"]["code"] == "candidate_budget"
    assert "candidate_leads" not in encoded(prior) and not toolkit.seen
    change_event(store, "previous", "empty_evidence_review", lambda d: d.update(candidate_budget=25))
    assert load_prior_attempt_feedback(toolkit) is None


def test_empty_feedback_keeps_existing_event_and_payload_budgets(store):
    attempt(store, "previous", events=empty_history(store) * 3)
    assert load_prior_attempt_feedback(fresh(store)) is None


@pytest.mark.parametrize("field,value", [
    ("source_photo_id", "b"), ("source_version", "old"), ("gallery_revision", -1),
    ("agent_spec", 17), ("retrieval_policy", "old-policy"), ("logical_model", "other-model"),
    ("cache_key", "foreign-key"), ("feedback_version", 999), ("feedback_version", True),
    ("corpus_digest", "foreign-corpus"),
])
def test_foreign_or_obsolete_execution_identity_is_never_inferred(store, field, value):
    attempt(store, "previous")
    change_event(store, "previous", IDENTITY_EVENT, lambda d: d.update({field: value}))
    assert load_prior_attempt_feedback(fresh(store)) is None


@pytest.mark.parametrize("changes", [
    {"direction": "same_moment"}, {"year": 2020},
    {"anchor": SemanticAnchor(photo_id="b")},
    {"anchor": SemanticAnchor(photo_id="a", label="different selected label")},
    {"anchor": SemanticAnchor(photo_id="a", kind="text")},
    {"anchor": SemanticAnchor(photo_id="a", region_id="other-region")},
    {"anchor": SemanticAnchor(photo_id="a", box=Box(x=0, y=0, width=.5, height=.5))},
])
def test_selection_scope_must_match_exactly(store, changes):
    attempt(store, "previous")
    assert load_prior_attempt_feedback(fresh(store, request(**changes))) is None


def test_ui_request_revision_does_not_change_execution_identity_or_ready_cache_key(store, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "fixture-logical-model")
    req = attempt(store, "previous")
    toolkit = fresh(store, request(request_revision=87))
    assert load_prior_attempt_feedback(toolkit)["prior_run_id"] == "previous"
    value = req.explore.model_dump()
    value.pop("request_revision")
    value["photo_version"] = store.photo("a").version
    original_key = hashlib.sha256(encoded([f"agent-spec-v{AGENT_SPEC_VERSION}", RETRIEVAL_POLICY,
                                          "fixture-logical-model", value]).encode()).hexdigest()
    assert RunService(store, None).cache_key(req) == original_key
    assert execution_identity(store, req)["cache_key"] == original_key
    assert AGENT_SPEC_VERSION == 18


@pytest.mark.parametrize("which", ["previous", "current"])
def test_identityless_history_and_direct_runner_calls_do_not_receive_guessed_feedback(store, which):
    attempt(store, "previous", identity=which != "previous")
    assert load_prior_attempt_feedback(fresh(store, identity=which != "current")) is None


@pytest.mark.parametrize("mutation", ["delete", "version", "access", "year"])
def test_deleted_changed_or_newly_unauthorized_photos_invalidate_prior_snapshot(store, mutation):
    attempt(store, "previous")
    if mutation == "delete":
        store.delete("b")
    else:
        value = store.photo("b").model_dump(mode="json")
        if mutation == "version":
            value["version"] = "new-version"
        elif mutation == "access":
            value["device_id"] = "another-device"
        else:
            value["captured_at"] = "2018-01-01T00:00:00+00:00"
        # Deliberately omit the revision bump: the corpus digest is independent.
        store.write("UPDATE photos SET data=? WHERE id='b'", (encoded(value),))
    assert load_prior_attempt_feedback(fresh(store)) is None


@pytest.mark.parametrize("kind,mutate", [
    ("evidence_review", lambda d: d["decisions"][0].update(photo_id="foreign")),
    ("evidence_review", lambda d: d["decisions"][0].update(photo_id="a")),
    ("evidence_review", lambda d: d.update(accepted_count=1)),
    ("evidence_review", lambda d: d["decisions"][0].update(reason="x" * 1201)),
    ("group_proposal", lambda d: d["groups"][0].update(photo_ids=["foreign", "c"])),
    ("group_proposal", lambda d: d["retained_items"][0].update(photo_id="foreign")),
    ("group_evidence_review", lambda d: d["member_reviews"][0].update(group_id="foreign")),
    ("group_evidence_review", lambda d: d["member_reviews"][0].update(photo_id="foreign")),
    ("group_evidence_review", lambda d: d.update(supported=True)),
    ("grouping_failed", lambda d: d.update(code="x" * 50_000)),
])
def test_malformed_unpaired_oversized_or_unavailable_members_reject_whole_latest_bundle(store, kind, mutate):
    attempt(store, "earlier-valid")
    attempt(store, "latest-invalid")
    change_event(store, "latest-invalid", kind, mutate)
    assert load_prior_attempt_feedback(fresh(store)) is None  # Do not cherry-pick an older attempt.


def test_forged_identity_for_a_different_run_request_and_duplicate_identity_are_rejected(store):
    attempt(store, "previous")
    foreign = request(direction="same_moment")
    store.write("UPDATE runs SET request=? WHERE id='previous'", (foreign.model_dump_json(),))
    toolkit = fresh(store)
    assert load_prior_attempt_feedback(toolkit) is None
    store.write("UPDATE runs SET request=? WHERE id='previous'", (request().model_dump_json(),))
    store.event("previous", IDENTITY_EVENT, execution_identity(store, request()))
    assert load_prior_attempt_feedback(toolkit) is None


def test_unreviewed_final_omissions_stay_proposals_and_do_not_prove_empty(store):
    events = history()[:-1]
    events.append(("group_proposal", {"attempt": 2, "groups": [], "accepted_photo_ids": ["b", "c"],
                                    "retained_items": [], "omitted": [
                                        {"photo_id": pid, "verdict": "uncertain", "reason": MARKER} for pid in ("b", "c")]}))
    events.append(("grouping_failed", {"code": "empty_revision", "stage": "proposal"}))
    attempt(store, "previous", events=events)
    toolkit = fresh(store)
    prior = load_prior_attempt_feedback(toolkit)
    assert prior["events"][-2]["data"]["omitted"][0]["verdict"] == "uncertain"
    assert len([e for e in prior["events"] if e["kind"] == "group_evidence_review"]) == 1
    assert not toolkit.seen and not toolkit.covered and not toolkit.searched
    with pytest.raises(ValueError):
        toolkit.submit_exploration_result(ExplorationResult(label="history only", items=[{"photo_id": "b", "reason": MARKER}]))
    with pytest.raises(ValueError, match="Unsearched"):
        toolkit.submit_exploration_result(ExplorationResult(label="history only", items=[], complete=True))


def test_resume_keeps_its_original_optional_feedback_selection(store):
    attempt(store, "previous")
    toolkit = fresh(store)
    store.event("current", "prior_attempt_feedback_used", {"version": RETRY_FEEDBACK_VERSION, "prior_run_id": "previous"})
    attempt(store, "later")
    assert load_prior_attempt_feedback(toolkit)["prior_run_id"] == "previous"
    change_event(store, "current", "prior_attempt_feedback_used", lambda d: d.update(prior_run_id=None))
    assert load_prior_attempt_feedback(toolkit) is None


def test_execution_identity_is_written_once_and_cannot_adopt_a_changed_snapshot_on_resume(store):
    toolkit = fresh(store)
    record_execution_identity(store, "current", toolkit.request)
    assert len(store.rows("SELECT * FROM events WHERE run_id='current' AND kind=?", (IDENTITY_EVENT,))) == 1
    store.upsert(asset("new"))
    with pytest.raises(ValueError, match="snapshot changed"):
        record_execution_identity(store, "current", toolkit.request)


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_kind", ["group", "empty"])
async def test_explorer_and_organizer_proposers_see_history_but_both_independent_reviewers_are_fresh(store, monkeypatch, prior_kind):
    attempt(store, "previous", events=empty_history(store) if prior_kind == "empty" else history())
    loads = []
    original_loader = load_prior_attempt_feedback

    def counted_loader(toolkit):
        loads.append(toolkit.run_id)
        return original_loader(toolkit)

    monkeypatch.setattr("connected_gallery.agent_runtime.runner.load_prior_attempt_feedback", counted_loader)

    class Explorer(RetrievalGateway):
        async def invoke(self, messages, schemas):
            assert MARKER in encoded([m.content for m in messages])
            assert "gives no inspection" in encoded([m.content for m in messages])
            return await super().invoke(messages, schemas)

    class CandidateVerifier:
        async def invoke(self, messages, schemas):
            assert MARKER not in encoded([m.content for m in messages])
            assert "prior_attempt_feedback" not in encoded([m.content for m in messages])
            return response("submit_candidate_review", {"selected_meaning": "fresh selected crop", "anchor_supported": True,
                            "decisions": [{"index": i, "verdict": "supported", "reason": "fresh comparison"} for i in range(2)]})

    class Organizer(RevisionGateway):
        async def invoke(self, messages, schemas):
            serialized = encoded([m.content for m in messages])
            assert (MARKER in serialized) == (schemas[0]["name"] != "submit_group_member_review")
            return await super().invoke(messages, schemas)

    gateway = Organizer()
    runner = GraphAgentRunner(store, None, Explorer(), reviewer=EvidenceReviewer(CandidateVerifier()),
                              result_organizer=ResultOrganizer(gateway))
    service = RunService(store, runner)
    run = service.start(request())
    await service.tasks[run["id"]]
    actual = service.get(run["id"])
    assert actual["status"] == "completed", actual
    assert loads == [run["id"]]
    assert len(gateway.compared) == 3 and gateway.proposals == 2
    assert actual["result"]["items"][0]["photo_id"] == "b"
    assert MARKER not in encoded(actual["result"])
    assert len(store.rows("SELECT * FROM events WHERE run_id=? AND kind=?", (run["id"], IDENTITY_EVENT))) == 1
    assert json.loads(store.rows("SELECT data FROM events WHERE run_id=? AND kind='prior_attempt_feedback_used'", (run["id"],))[0]["data"])["prior_run_id"] == "previous"
    before = store.db.total_changes
    assert service.ready(request().explore)["state"] == "ready"
    assert store.db.total_changes == before


@pytest.mark.asyncio
async def test_current_independent_empty_review_receives_no_prior_empty_leads_or_ledger(store):
    from test_empty_evidence import Judge
    attempt(store, "previous", events=empty_history(store))
    toolkit = fresh(store)
    toolkit.prior_attempt_feedback = load_prior_attempt_feedback(toolkit)
    class FreshJudge(Judge):
        async def invoke(self, messages, schemas):
            serialized = encoded([message.content for message in messages])
            assert MARKER not in serialized and "candidate_leads" not in serialized
            assert "prior_attempt_feedback" not in serialized
            return await super().invoke(messages, schemas)
    judge = FreshJudge(verdict="possible_relation")
    result = await EvidenceReviewer(judge).review(toolkit, toolkit.request, {"label": "empty proposal", "items": [], "complete": True})
    assert judge.calls == 1 and judge.image_counts == [4]
    assert not result["complete"] and "empty_evidence" not in result
    assert not toolkit.seen and not toolkit.covered and not toolkit.searched


@pytest.mark.asyncio
async def test_preparation_report_records_actual_run_id_for_followup_diagnosis(tmp_path, monkeypatch):
    from connected_gallery.adapters.store import Store
    prepare = script("prepare-demo.py")
    data = tmp_path / "synthetic"
    setup = Store(data)
    setup.upsert(asset())
    region = {"id": "region", "photo_id": "a", "box": {"x": 0, "y": 0, "width": 1, "height": 1},
              "kind": "object", "label": "visible fixture", "evidence": "fixture"}
    setup.write("INSERT INTO analyses VALUES(?,?)", ("a", encoded({"regions": [region]})))
    setup.close()
    (data / "synthetic-demo.json").write_text('{"synthetic":true}', encoding="utf-8")
    for name in ("CG_AUTO_ORGANIZE", "CG_ANALYSIS_CONCURRENCY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, os.getenv(name, ""))

    class NoModelRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, rid, req):
            return {"label": "incomplete fixture", "items": [], "complete": False,
                    "groups": [], "grouping_status": "failed"}

    monkeypatch.setattr("connected_gallery.adapters.models.LocalModels", lambda *args: None)
    monkeypatch.setattr("connected_gallery.adapters.proxy.ProxyGateway", lambda **kwargs: SimpleNamespace(primary="fixture-model"))
    monkeypatch.setattr("connected_gallery.agent_runtime.runner.GraphAgentRunner", NoModelRunner)
    args = SimpleNamespace(env_file=None, model_dir=None, model=None, data_dir=str(data), stage="prepare",
                           photo_id=None, region_id=None, limit=None, workers=1, grouping_timeout_seconds=45)
    await prepare.main(args)
    report = json.loads((data / "preparation-report.json").read_text(encoding="utf-8"))
    check = Store(data)
    try:
        rid = report["connections"]["region"]["run_id"]
        assert check.rows("SELECT status FROM runs WHERE id=?", (rid,))[0]["status"] == "incomplete"
        assert len(check.rows("SELECT data FROM events WHERE run_id=? AND kind=?", (rid, IDENTITY_EVENT))) == 1
    finally:
        check.close()
