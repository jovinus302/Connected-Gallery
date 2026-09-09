"""Latency work must not buy speed with lost or invented evidence.

Reused OCR lines, host-supplied leads, concurrent tool execution and rendering
memoisation each keep the observable contract: same coordinate space, same
budgets, same submission credit, same response order.
"""
import io
import json
import time as clock

import pytest
from langchain_core.messages import AIMessage
from PIL import Image

from connected_gallery.adapters.store import encoded
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.domain.models import Box, ExploreInput, RunRequest, SemanticAnchor
from connected_gallery.gallery_tools.registry import GalleryTools, RecognizeTextArgs

from test_contracts import store
from test_indexing import Models


PAGE = [("가게", .91, (.05, .05, .25, .15)),
        ("이름", .92, (.10, .06, .30, .16)),
        ("바깥", .93, (.38, .05, .48, .15)),
        ("아래", .94, (.70, .70, .90, .90))]

INSIDE = Box(x=0, y=0, width=.4, height=.3)
EMPTY_REGION = Box(x=.45, y=.35, width=.2, height=.2)


class CountingOCR:
    """PaddleOCR-shaped evidence in the pixels of whatever image it is given."""

    def __init__(self, lines=PAGE):
        self.lines, self.sizes = lines, []

    def ocr(self, image):
        self.sizes.append(image.size)
        w, h = image.size
        return {"pages": [{"res": {
            "rec_texts": [t for t, _, _ in self.lines],
            "rec_scores": [s for _, s, _ in self.lines],
            "rec_boxes": [[x1 * w, y1 * h, x2 * w, y2 * h]
                          for _, _, (x1, y1, x2, y2) in self.lines]}}]}


def wide(store, photo_id="a", size=(200, 80)):
    # Non-square on purpose: a width/height mix-up cannot stay invisible.
    payload = io.BytesIO()
    Image.new("RGB", size, "red").save(payload, "JPEG")
    store.put_image(photo_id, payload.getvalue())


def analyst(store, models, run_id):
    return GalleryTools(store, models, RunRequest(role="analyst", photo_ids=["a"]), run_id)


def test_region_text_reuses_stored_full_photo_lines_without_new_inference(store):
    wide(store)
    ocr = CountingOCR()
    tools = analyst(store, ocr, "ocr-reuse")

    whole = tools.recognize_text(RecognizeTextArgs(photo_id="a"))
    assert len(ocr.sizes) == 1 and ocr.sizes[0] == (200, 80)
    assert whole["source"] == "region_ocr" and len(whole["texts"]) == 4

    for _ in range(2):
        region = tools.recognize_text(RecognizeTextArgs(photo_id="a", box=INSIDE))
        assert len(ocr.sizes) == 1  # No further OCR inference at all.
        assert region["source"] == "full_photo_ocr"
        assert region["coordinate_space"] == "full_oriented_photo_normalized_xywh"
        assert [t["text"] for t in region["texts"]] == ["가게", "이름"]
        assert [t["score"] for t in region["texts"]] == [.91, .92]
        assert region["texts"][0]["box"] == pytest.approx(
            dict(x=.05, y=.05, width=.20, height=.10))
        assert region["texts"][1]["box"] == pytest.approx(
            dict(x=.10, y=.06, width=.20, height=.10))


def test_region_without_reusable_lines_falls_back_to_one_cached_crop_pass(store):
    wide(store)
    ocr = CountingOCR()
    tools = analyst(store, ocr, "ocr-fallback")
    tools.recognize_text(RecognizeTextArgs(photo_id="a"))

    empty = tools.recognize_text(RecognizeTextArgs(photo_id="a", box=EMPTY_REGION))
    assert empty["source"] == "region_ocr" and len(ocr.sizes) == 2
    assert ocr.sizes[1] == (40, 16)  # The exact crop, not the full photo.
    assert tools.recognize_text(RecognizeTextArgs(photo_id="a", box=EMPTY_REGION)) == empty
    assert len(ocr.sizes) == 2  # The region artifact key still caches it.


def test_refresh_forces_the_exact_crop_and_missing_full_evidence_behaves_as_before(store):
    wide(store)
    ocr = CountingOCR()
    tools = analyst(store, ocr, "ocr-refresh")
    tools.recognize_text(RecognizeTextArgs(photo_id="a"))

    forced = tools.recognize_text(RecognizeTextArgs(photo_id="a", box=INSIDE, refresh=True))
    assert forced["source"] == "region_ocr" and len(ocr.sizes) == 2 and ocr.sizes[1] == (80, 24)
    # refresh is a request flag, never part of the artifact identity.
    assert tools.recognize_text(RecognizeTextArgs(photo_id="a", box=INSIDE, refresh=True)) == forced
    assert len(ocr.sizes) == 2
    # A photo the analyst never recognized keeps today's crop cost and shape.
    other = tools.recognize_text(RecognizeTextArgs(photo_id="b", box=INSIDE))
    assert other["source"] == "region_ocr" and len(ocr.sizes) == 3 and ocr.sizes[2] == (40, 30)
    assert other["texts"][0]["box"] == pytest.approx(dict(x=.02, y=.015, width=.08, height=.03))


def vectors(store):
    store.vector("b:image", "b", "visual-test", [1, 0])
    store.vector("c:image", "c", "visual-test", [.9, .1])


SUBMIT_B = {"name": "submit_exploration_result", "id": "submit", "type": "tool_call",
            "args": {"label": "초기 후보", "complete": True,
                     "items": [{"photo_id": "b", "reason": "첨부된 이미지를 확인했습니다."}]}}


class Recording:
    def __init__(self):
        self.calls, self.initial, self.budget = 0, None, None

    def record(self, messages):
        self.calls += 1
        if self.calls == 1:
            self.budget = messages[1].content
            self.initial = messages[2].content


class FirstResponseSubmit(Recording):
    """Submits immediately, so only host-supplied evidence can support it."""

    async def invoke(self, messages, schemas):
        self.record(messages)
        return AIMessage(content="", tool_calls=[SUBMIT_B])


class InspectThenSubmit(Recording):
    """Without a host supply the model must observe candidates itself."""

    async def invoke(self, messages, schemas):
        self.record(messages)
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "inspect_photos", "args": {"photo_ids": ["b"]},
                "id": "inspect", "type": "tool_call"}])
        return AIMessage(content="", tool_calls=[SUBMIT_B])


def blocks(content, key):
    return [json.loads(b["text"])[key] for b in content
            if b.get("type") == "text" and key in json.loads(b["text"])]


def events(store, kind):
    return [json.loads(r["data"]) for r in
            store.rows("SELECT data FROM events WHERE kind=? ORDER BY seq", (kind,))]


async def explore(store, gateway, run_id):
    request = RunRequest(role="explorer",
                         explore=ExploreInput(anchor=SemanticAnchor(photo_id="a")))
    return await GraphAgentRunner(store, Models(), gateway).execute(run_id, request)


@pytest.mark.asyncio
async def test_initial_candidates_supply_images_without_spending_budget_or_credit(store, monkeypatch):
    monkeypatch.delenv("CG_EXPLORE_INITIAL_CANDIDATES", raising=False)
    vectors(store)
    gateway = FirstResponseSubmit()
    result = await explore(store, gateway, "leads")

    assert gateway.calls == 1 and result["items"][0]["photo_id"] == "b"
    supply = blocks(gateway.initial, "initial_candidates")[0]
    assert supply["count"] == 2 and supply["limit"] == 8
    assert supply["channels"]["visual"] == 2 and supply["channel_errors"] == {}
    assert supply["coverage"]["visual"] == {"indexed_count": 2, "eligible_count": 2,
                                            "unindexed_count": 0}
    assert "not accepted results" in supply["instruction"]
    assert "verify the selected meaning" in supply["instruction"]
    leads = blocks(gateway.initial, "initial_candidate")
    assert [c["photo_id"] for c in leads] == ["b", "c"]
    assert all("visual" in c["channels"] for c in leads)
    assert sum(b.get("type") == "image" for b in gateway.initial) == 3  # anchor + 2 leads

    # Budget wording on the first response is untouched by the supply.
    assert "6 model responses" in gateway.budget and "12 tool calls remain" in gateway.budget
    tool_events = events(store, "tool")
    supplied = [e for e in tool_events if e["name"] == "initial_candidates"]
    assert len(supplied) == 1 and supplied[0]["seen"] == ["a", "b", "c"]
    assert all(e["covered"] == [] and e["searched"] == [] for e in tool_events)
    recorded = events(store, "initial_candidates")
    assert len(recorded) == 1 and recorded[0]["count"] == 2 and recorded[0]["limit"] == 8
    assert recorded[0]["channels"]["visual"] == 2
    assert recorded[0]["seconds"] >= recorded[0]["retrieval_seconds"] >= 0
    assert recorded[0]["render_seconds"] >= 0
    assert recorded[0]["text_queries"] == {"label": True, "ocr": False}


@pytest.mark.asyncio
async def test_initial_candidate_supply_is_disabled_by_its_own_setting(store, monkeypatch):
    monkeypatch.setenv("CG_EXPLORE_INITIAL_CANDIDATES", "0")
    vectors(store)
    gateway = InspectThenSubmit()
    assert (await explore(store, gateway, "leads-off"))["complete"]
    assert blocks(gateway.initial, "initial_candidates") == []
    assert events(store, "initial_candidates") == []
    assert [e["name"] for e in events(store, "tool")] == [
        "initial_photo", "inspect_photos", "submit_exploration_result"]


@pytest.mark.asyncio
async def test_unindexed_gallery_reports_empty_leads_with_its_coverage(store, monkeypatch):
    monkeypatch.delenv("CG_EXPLORE_INITIAL_CANDIDATES", raising=False)
    gateway = InspectThenSubmit()
    assert (await explore(store, gateway, "leads-empty"))["complete"]
    supply = blocks(gateway.initial, "initial_candidates")[0]
    assert supply["count"] == 0 and supply["channel_errors"] == {}
    assert supply["coverage"] == {"visual": {"indexed_count": 0, "eligible_count": 2,
                                             "unindexed_count": 2},
                                  "text": {"indexed_count": 0, "eligible_count": 2,
                                           "unindexed_count": 2}}
    assert blocks(gateway.initial, "initial_candidate") == []
    assert events(store, "initial_candidates")[0]["count"] == 0
    assert [e["name"] for e in events(store, "tool")] == [
        "initial_photo", "inspect_photos", "submit_exploration_result"]


def slow_inspect(order, seconds=.3):
    original = GalleryTools.inspect_photos

    def inspect(self, args):
        order.append("inspect:" + ",".join(args.photo_ids))
        clock.sleep(seconds)
        return original(self, args)

    return inspect


@pytest.mark.asyncio
async def test_independent_calls_before_a_submission_run_once_and_together(store, monkeypatch):
    monkeypatch.setenv("CG_EXPLORE_INITIAL_CANDIDATES", "0")
    order, spans = [], []
    monkeypatch.setattr(GalleryTools, "inspect_photos", slow_inspect(order))

    class Batching:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            spans.append(clock.monotonic())
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "inspect_photos", "args": {"photo_ids": ["b"]},
                     "id": "first", "type": "tool_call"},
                    {"name": "inspect_photos", "args": {"photo_ids": ["c"]},
                     "id": "second", "type": "tool_call"},
                    {"name": "inspect_photos", "args": {"photo_ids": ["b"]},
                     "id": "repeat", "type": "tool_call"}])
            return AIMessage(content="", tool_calls=[{
                "name": "submit_exploration_result", "id": "submit", "type": "tool_call",
                "args": {"label": "동시 실행", "complete": True,
                         "items": [{"photo_id": "b", "reason": "이미지를 확인했습니다."}]}}])

    gateway = Batching()
    result = await explore(store, gateway, "concurrent")
    assert result["complete"] and gateway.calls == 2
    assert spans[1] - spans[0] < .5  # Three calls, two 0.3s observations.
    assert order == ["inspect:b", "inspect:c"]  # The duplicate ran once.

    timings = events(store, "tool_timing")
    assert [t["name"] for t in timings] == ["inspect_photos"] * 3 + ["submit_exploration_result"]
    assert [t.get("concurrent") for t in timings] == [True, True, True, None]


@pytest.mark.asyncio
async def test_a_submission_still_separates_the_calls_around_it(store, monkeypatch):
    monkeypatch.setenv("CG_EXPLORE_INITIAL_CANDIDATES", "0")
    order = []
    monkeypatch.setattr(GalleryTools, "inspect_photos", slow_inspect(order, seconds=.01))
    original_submit = GalleryTools.submit_exploration_result

    def submit(self, args):
        order.append("submit")
        return original_submit(self, args)

    monkeypatch.setattr(GalleryTools, "submit_exploration_result", submit)

    class Mixed:
        calls = 0

        async def invoke(self, messages, schemas):
            self.calls += 1
            return AIMessage(content="", tool_calls=[
                {"name": "inspect_photos", "args": {"photo_ids": ["b"]},
                 "id": "before", "type": "tool_call"},
                {"name": "submit_exploration_result", "id": "submit", "type": "tool_call",
                 "args": {"label": "제출", "complete": True,
                          "items": [{"photo_id": "b", "reason": "이미지를 확인했습니다."}]}},
                {"name": "inspect_photos", "args": {"photo_ids": ["c"]},
                 "id": "after", "type": "tool_call"}])

    result = await explore(store, Mixed(), "mixed-batch")
    assert result["complete"] and order == ["inspect:b", "submit", "inspect:c"]


@pytest.mark.asyncio
async def test_batch_keeps_call_order_ids_and_the_reserved_submission_budget(store, monkeypatch):
    monkeypatch.setenv("CG_EXPLORE_INITIAL_CANDIDATES", "0")
    order = []
    monkeypatch.setattr(GalleryTools, "inspect_photos", slow_inspect(order, seconds=0))

    class Flooding:
        calls = 0

        def __init__(self):
            self.returned = None

        async def invoke(self, messages, schemas):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "inspect_photos", "args": {"photo_ids": ["b"]},
                     "id": f"call-{n}", "type": "tool_call"} for n in range(14)])
            self.returned = [m for m in messages if getattr(m, "tool_call_id", None)]
            return AIMessage(content="", tool_calls=[{
                "name": "submit_exploration_result", "id": "submit", "type": "tool_call",
                "args": {"label": "예산", "complete": True,
                         "items": [{"photo_id": "b", "reason": "이미지를 확인했습니다."}]}}])

    gateway = Flooding()
    assert (await explore(store, gateway, "flooded"))["complete"]
    assert [m.tool_call_id for m in gateway.returned] == [f"call-{n}" for n in range(14)]
    reserved = encoded({"error": "Tool budget reserved for submission. Submit current evidence now."})
    assert [m.content for m in gateway.returned][11:] == [reserved] * 3
    assert order == ["inspect:b"]  # One observation, eleven budgeted calls.
    assert len(events(store, "tool_timing")) == 12


def test_repeated_image_blocks_render_each_photo_and_crop_once(store, monkeypatch):
    reads, read = [], store.read_image

    def counted(photo_id, box=None):
        reads.append((photo_id, box))
        return read(photo_id, box)

    monkeypatch.setattr(store, "read_image", counted)
    tools = analyst(store, None, "render-memo")
    crop = Box(x=0, y=0, width=.5, height=.5)

    first, second = tools.image_block("a"), tools.image_block("a")
    assert first[1]["source"]["data"] == second[1]["source"]["data"]
    assert reads == [("a", None)]
    cropped = tools.image_block("a", crop)
    assert cropped[1]["source"]["data"] != first[1]["source"]["data"]
    assert reads == [("a", None), ("a", crop)]
    tools.image_block("a", crop)
    tools.image_block("b")
    assert reads == [("a", None), ("a", crop), ("b", None)]
    # The metadata block is rebuilt, so a new analysis is still transported.
    assert json.loads(first[0]["text"])["analysis"] is None


class Recall:
    """Records the text queries in the order the channels issue them."""

    visual_space, text_space = "visual-test", "text-test"

    def __init__(self):
        self.queries = []

    def image(self, image):
        raise RuntimeError("visual index unavailable in this fixture")

    def text(self, text, query=False):
        self.queries.append(text)
        return self.text_space, [1, 0] if text == LABEL else [0, 1]


LABEL = "제주 빛산책"
COMMON = "제주"


def text_anchor(store, label=LABEL):
    tools = GalleryTools(
        store, Recall(),
        RunRequest(role="explorer", explore=ExploreInput(
            anchor=SemanticAnchor(photo_id="a", label=label,
                                  box=Box(x=0, y=0, width=.4, height=.3)))),
        "text-leads")
    return tools


def stored_ocr(store, tools):
    """One full-photo OCR artifact whose in-box text is the common token."""
    wide(store)
    tools.versions = {p.id: p.version for p in store.photos()}
    tools.models_ocr = CountingOCR([(COMMON, .9, (.05, .05, .25, .15))])
    saved = tools.models
    tools.models = tools.models_ocr
    tools.recognize_text(RecognizeTextArgs(photo_id="a"))
    tools.models = saved


def test_label_query_runs_first_and_ocr_text_only_adds_a_second_query(store):
    tools = text_anchor(store)
    stored_ocr(store, tools)
    store.vector("b:label", "b", "text-test", [1, 0])
    # b carries the whole label, c only the common token the region OCR yields.
    store.write("INSERT INTO evidence_fts VALUES(?,?)", ("b", LABEL))
    store.write("INSERT INTO evidence_fts VALUES(?,?)", ("c", COMMON))

    leads = tools.initial_candidates(tools.request.explore.anchor, 8)
    # Only the semantic channel embeds; the literal channel queries FTS directly.
    assert tools.models.queries == [LABEL, COMMON]
    assert leads["text_queries"] == {"label": True, "ocr": True}
    assert [c["photo_id"] for c in leads["candidates"]] == ["b", "c"]
    assert leads["candidates"][0]["query_source"] == "label"
    assert leads["candidates"][1]["query_source"] == "ocr"
    assert leads["channel_errors"]["visual"] == "RuntimeError"  # Channels stay isolated.


def test_an_empty_label_leaves_only_the_recognized_text_query(store):
    tools = text_anchor(store, label="")
    stored_ocr(store, tools)
    store.vector("c:common", "c", "text-test", [0, 1])

    leads = tools.initial_candidates(tools.request.explore.anchor, 8)
    assert tools.models.queries == [COMMON]
    assert leads["text_queries"] == {"label": False, "ocr": True}
    assert [c["query_source"] for c in leads["candidates"]] == ["ocr"]


def test_without_recognized_text_the_label_is_the_only_query(store):
    tools = text_anchor(store)
    store.vector("b:label", "b", "text-test", [1, 0])

    leads = tools.initial_candidates(tools.request.explore.anchor, 8)
    assert tools.models.queries == [LABEL]
    assert leads["text_queries"] == {"label": True, "ocr": False}
    assert [c["query_source"] for c in leads["candidates"]] == ["label"]


def test_a_photo_whose_block_cannot_be_built_is_never_credited_as_observed(store, monkeypatch):
    analysis = store.analysis

    def broken(photo_id):
        if photo_id == "b":
            raise ValueError("corrupt stored analysis")
        return analysis(photo_id)

    monkeypatch.setattr(store, "analysis", broken)
    tools = analyst(store, None, "unbuildable-block")
    with pytest.raises(ValueError, match="corrupt stored analysis"):
        tools.image_block("b")
    assert "b" not in tools.seen
    with pytest.raises(ValueError, match="corrupt stored analysis"):
        tools.invoke("inspect_photos", {"photo_ids": ["c", "b"]})
    assert tools.seen == {"c"}  # The photo actually built stays observed.


@pytest.mark.asyncio
async def test_initial_supply_skips_an_unattachable_lead_without_granting_it_credit(store, monkeypatch):
    monkeypatch.delenv("CG_EXPLORE_INITIAL_CANDIDATES", raising=False)
    vectors(store)
    analysis = store.analysis

    def broken(photo_id):
        if photo_id == "c":
            raise ValueError("corrupt stored analysis")
        return analysis(photo_id)

    monkeypatch.setattr(store, "analysis", broken)
    gateway = FirstResponseSubmit()
    assert (await explore(store, gateway, "unattachable-lead"))["items"][0]["photo_id"] == "b"
    supply = blocks(gateway.initial, "initial_candidates")[0]
    assert supply["count"] == 1 and supply["channel_errors"]["images"] == "ValueError"
    assert [c["photo_id"] for c in blocks(gateway.initial, "initial_candidate")] == ["b"]
    supplied = [e for e in events(store, "tool") if e["name"] == "initial_candidates"]
    assert supplied[0]["seen"] == ["a", "b"]  # c was never attached, so never seen.
