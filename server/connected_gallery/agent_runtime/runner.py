from __future__ import annotations
import asyncio
import json
import os
import time
from typing import Annotated, TypedDict
from pydantic import ValidationError
import aiosqlite
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from connected_gallery.agent_specs.prompts import PROMPTS
from connected_gallery.agent_specs.versions import AGENT_SPEC_VERSION
from connected_gallery.gallery_tools.registry import GalleryTools
from connected_gallery.adapters.store import encoded
from connected_gallery.application.attempt_feedback import RETRY_FEEDBACK_VERSION, load_prior_attempt_feedback, feedback_block


class State(TypedDict):
    messages: Annotated[list, add_messages]
    turns: int
    calls: int
    spec_version: int
    repair_pending: bool
    repair_used: bool
    review_attempts: int
    submission_reminded: bool


def validate_exploration_responses(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 6 <= value <= 12:
        raise ValueError("Exploration responses must be an integer from 6 to 12")
    return value


class GraphAgentRunner:
    def __init__(self, store, models, gateway, reviewer=None, explorer_gateway=None, space_reviewer=None, result_organizer=None, context_agent=None, exploration_responses=6):
        self.exploration_responses = validate_exploration_responses(exploration_responses)
        self.store = store
        self.models = models
        self.gateway = gateway
        self.reviewer = reviewer
        self.explorer_gateway = explorer_gateway or gateway
        self.space_reviewer = space_reviewer
        if result_organizer is not None and reviewer is None:
            raise ValueError("Result organization requires independent candidate review")
        self.result_organizer = result_organizer
        self.context_agent = context_agent
        # Every saver targets the same file. Serialize its short DB operations,
        # while keeping model calls and tool execution concurrent.
        self.checkpoint_lock = asyncio.Lock()

    async def execute(self, run_id, request):
        if request.role == "context":
            from connected_gallery.agent_runtime.context import PhotoContextAgent
            from connected_gallery.adapters.proxy import ProxyGateway
            from connected_gallery.application.demo_profile import effective_context_model
            agent = self.context_agent
            if agent is None:
                gateway = self.gateway
                # Only the production transport is replaced. Explicit custom
                # gateways/agents remain injectable and never cause live calls.
                if type(gateway) is ProxyGateway and "CG_CONTEXT_MODEL" in os.environ:
                    gateway = ProxyGateway(attempt_timeout=gateway.attempt_timeout,
                        primary=effective_context_model(), fallback=None, repeat_primary=False)
                agent = PhotoContextAgent(self.store, self.models, gateway)
            return await agent.execute(run_id, request)
        # Asset versions alone do not cover replacement previews, updated
        # analyses or changes to the candidate corpus. Retain the revision from
        # BEFORE retrieval, rather than adopting a newer one after review.
        exploration_revision = self.store.revision if request.role == "explorer" else None
        toolkit = GalleryTools(self.store, self.models, request, run_id)
        toolkit.prior_attempt_feedback = load_prior_attempt_feedback(toolkit)
        if request.role == "explorer" and not self.store.rows(
            "SELECT 1 FROM events WHERE run_id=? AND kind='prior_attempt_feedback_used'", (run_id,)
        ):
            self.store.event(run_id, "prior_attempt_feedback_used", {
                "version": RETRY_FEEDBACK_VERSION,
                "prior_run_id": toolkit.prior_attempt_feedback["prior_run_id"] if toolkit.prior_attempt_feedback else None,
            })
        toolkit.defer_results = request.role == "explorer" and self.reviewer is not None
        toolkit.defer_spaces = request.role == "organizer" and self.space_reviewer is not None
        for row in self.store.rows(
            "SELECT data FROM events WHERE run_id=? AND kind='tool'", (run_id,)
        ):
            data = json.loads(row["data"])
            toolkit.seen.update(data.get("seen", []))
            toolkit.covered.update(data.get("covered", []))
            toolkit.searched.update(data.get("searched", []))
        turns = {"analyst": 4, "explorer": self.exploration_responses, "organizer": 30}[request.role]
        max_calls = {"analyst": 12, "explorer": 2 * self.exploration_responses, "organizer": 100}[request.role]

        def require_current_corpus():
            if exploration_revision is not None and self.store.revision != exploration_revision:
                raise ValueError("Gallery changed during exploration; prepare again")

        async def model(state):
            repairing = (state.get("turns", 0) >= turns
                         and state.get("repair_pending", False)
                         and not state.get("repair_used", False))
            if state.get("turns", 0) >= turns and not repairing:
                raise RuntimeError("Submission validation repair exhausted" if state.get("repair_used") else "Model turn budget exceeded")
            self.store.event(
                run_id,
                "progress",
                {
                    "message": "사진의 연결을 살펴보고 있어요",
                    "turn": state.get("turns", 0) + 1,
                },
            )
            remaining = max(1, turns - state.get("turns", 0))
            finalizing = repairing or remaining == 1 or state.get("calls", 0) >= max_calls - 1
            budget = SystemMessage(content=(
                f"Execution budget: {remaining} model responses and "
                f"{max_calls - state.get('calls', 0)} tool calls remain. "
                + ("One validation-repair response is available. Correct the rejected submission "
                   "using the validation errors and evidence already observed. Only submit is available. "
                   "No new analysis, invented evidence, or further repair attempts are allowed."
                   if repairing else
                   "This is the final response: submit your evidence-grounded result now. "
                   "Record missing evidence as uncertainty; do not invent observations."
                   if finalizing else
                   "Reserve the last response for submission. Batch independent tool calls, "
                   "and submit as soon as enough evidence is available.")
            ))
            if request.role == "organizer":
                budget.content += " Current library coverage: " + encoded(toolkit.coverage_status())
            schemas = toolkit.schemas()
            if finalizing:
                schemas = [s for s in schemas if s["name"].startswith("submit_")]
            started = time.monotonic()
            messages = [state["messages"][0], budget, *state["messages"][1:]]
            if request.role == "explorer" and state.get("turns", 0) > 0:
                anchor = request.explore.anchor
                reference = await asyncio.to_thread(toolkit.image_block, anchor.photo_id, anchor.box)
                messages.append(HumanMessage(content=[{"type": "text", "text": encoded({
                    "immutable_selected_anchor": request.explore.model_dump(mode="json"),
                    "instruction": "This image is the user's original selected anchor, NOT a new candidate. Compare candidate photos against this reference. Candidate images never replace the anchor. The year restricts candidates only; it cannot change the selected person/object/text/place. Do not reinterpret unrelated candidates as the source. If evidence is insufficient, report incomplete or an evidence-supported empty result.",
                })}, *reference]))
            gateway = self.explorer_gateway if request.role == "explorer" else self.gateway
            response = await gateway.invoke(messages, schemas)
            self.store.event(run_id, "model_timing", {
                "turn": state.get("turns", 0) + 1,
                "seconds": round(time.monotonic() - started, 3),
                "finalizing": finalizing,
                "repair": repairing,
            })
            return {"messages": [response], "turns": state.get("turns", 0) + 1,
                    "repair_used": state.get("repair_used", False) or repairing,
                    "repair_pending": False}

        async def tools(state):
            messages = []
            calls = state.get("calls", 0)
            repair_pending = False
            repairing = state.get("turns", 0) > turns
            repair_submitted = False
            for call in state["messages"][-1].tool_calls:
                if repairing and (repair_submitted or not call["name"].startswith("submit_")):
                    messages.append(ToolMessage(content=encoded({"error": "Only a corrected submission is permitted."}), tool_call_id=call["id"]))
                    continue
                if repairing:
                    repair_submitted = True
                if calls >= max_calls - 1 and not call["name"].startswith("submit_"):
                    messages.append(ToolMessage(
                        content=encoded({"error": "Tool budget reserved for submission. Submit current evidence now."}),
                        tool_call_id=call["id"],
                    ))
                    continue
                calls += 1
                if calls > max_calls + int(repairing):
                    raise RuntimeError("Tool budget exceeded")
                started = time.monotonic()
                error = None
                try:
                    result = await asyncio.to_thread(
                        toolkit.invoke, call["name"], call["args"]
                    )
                    content = result if isinstance(result, list) else encoded(result)
                except Exception as e:
                    error = type(e).__name__
                    if call["name"].startswith("submit_") and isinstance(e, ValueError):
                        repair_pending = True
                    # Validation errors are useful to the model; infrastructure details are redacted.
                    if isinstance(e, ValidationError):
                        detail = {"error": "ValidationError", "issues": [
                            {"path": list(x["loc"]), "type": x["type"], "message": x["msg"]}
                            for x in e.errors(include_input=False, include_context=False, include_url=False)[:12]
                        ]}
                    else:
                        detail = {"error": str(e)[:300] if isinstance(e, ValueError) else error}
                    content = encoded(detail)
                    self.store.event(run_id, "tool_error", {"name": call["name"], **detail})
                self.store.event(run_id, "tool_timing", {
                    "name": call["name"],
                    "seconds": round(time.monotonic() - started, 3),
                    "error": error,
                })
                messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
            return {"messages": messages, "calls": calls, "repair_pending": repair_pending}

        def after_model(state):
            if state["messages"][-1].tool_calls:
                return "tools"
            if toolkit.result is not None and toolkit.defer_results:
                return "review"
            if (request.role in ("organizer", "explorer") and toolkit.result is None
                    and not state.get("submission_reminded", False)
                    and state.get("turns", 0) < turns):
                return "remind_submission"
            return END

        async def remind_submission(state):
            instruction = (
                "No exploration result has been submitted. A plain response cannot complete this run. "
                "Use the remaining response/tool budget to submit_exploration_result. "
                "Use only candidates whose images you actually inspected; preserve the original selected anchor. "
                "If evidence is missing, submit the confirmed partial items with complete=false, or an empty "
                "incomplete result. Do not invent matches or mark an unsearched library complete. "
                "This reminder is available once, within the original time, response and tool limits."
            ) if request.role == "explorer" else (
                "No Spaces have been saved. A plain response cannot complete this run. "
                "Use the remaining tool budget to finish library coverage and submit_space_proposal. "
                "Follow the most recent validation errors; do not invent evidence or skip unexamined photos. "
                "This reminder is available once, within the original time and response limits."
            )
            self.store.event(run_id, "submission_reminder", {"role": request.role,
                             "turns_used": state.get("turns", 0), "calls_used": state.get("calls", 0)})
            return {"submission_reminded": True, "messages": [HumanMessage(content=instruction)]}

        def after_tools(state):
            return (
                ("review" if toolkit.defer_results else END)
                if toolkit.result and (toolkit.result.get("complete", True)
                                       or state.get("turns", 0) >= turns)
                else "model"
            )

        async def review(state):
            require_current_corpus()
            reviewed = await self.reviewer.review(toolkit, request, toolkit.result)
            toolkit.authorize(request.explore.anchor.photo_id)
            require_current_corpus()
            attempts = state.get("review_attempts", 0) + 1
            # One evidence-guided refinement is available within the original
            # model/tool/time budgets. No keyword or semantic fallback is used.
            if (not reviewed["items"] and not reviewed.get("complete", False)
                    and getattr(toolkit, "review_anchor_supported", False)
                    and attempts < 2 and state.get("turns", 0) < turns - 1
                    and state.get("calls", 0) < max_calls - 2):
                toolkit.result = None
                return {"review_attempts": attempts, "messages": [HumanMessage(content=encoded({
                    "independent_visual_evidence": toolkit.review_feedback,
                    "instruction": ("Independent whole-gallery negative review found possible direct relationships or uncertainty. "
                        "These are investigation leads, not accepted photos. Preserve the original selected meaning, "
                        "distinguish identical products from related but different objects, inspect the leads yourself, "
                        "and resubmit only evidence you can support. Do not broaden to surrounding scenery or force "
                        "an empty result for completion. Submit incomplete if uncertainty remains."
                        if getattr(toolkit, "empty_review_status", None) == "needs_investigation" else
                        "None of the proposed candidates was visually supported. Keep the original selected meaning. Use this evidence to refine your retrieval and inspect new candidates if the remaining budget permits. Do not repeat unsupported claims or broaden to the surrounding scene. If evidence remains insufficient, submit incomplete."),
                }))]}
            if self.result_organizer is not None:
                reviewed = await self.result_organizer.organize(toolkit, request, reviewed)
            with self.store.lock:
                toolkit.authorize(request.explore.anchor.photo_id)
                for item in reviewed["items"]:
                    toolkit.authorize(item["photo_id"], source=False)
                require_current_corpus()
                toolkit.result = reviewed
                self.store.event(run_id, "results", reviewed)
            return {"review_attempts": attempts}

        def after_review(state):
            return END if toolkit.result is not None else "model"

        graph = StateGraph(State)
        graph.add_node("model", model)
        graph.add_node("tools", tools)
        graph.add_node("review", review)
        graph.add_node("remind_submission", remind_submission)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", after_model)
        graph.add_conditional_edges("tools", after_tools)
        graph.add_conditional_edges("review", after_review)
        graph.add_edge("remind_submission", "model")
        async with aiosqlite.connect(
            self.store.root / "checkpoints.sqlite"
        ) as connection:
            saver = AsyncSqliteSaver(connection)
            saver.lock = self.checkpoint_lock
            compiled = graph.compile(checkpointer=saver)
            config = {
                "configurable": {"thread_id": run_id},
                "recursion_limit": 2 * turns + 5,
            }
            checkpoint = await compiled.aget_state(config)
            if checkpoint.next and checkpoint.values.get("spec_version") != AGENT_SPEC_VERSION:
                # Old prompts/budgets must not resume halfway through the new graph.
                # Stored model artifacts survive; only this run's conversation resets.
                await saver.adelete_thread(run_id)
                checkpoint = await compiled.aget_state(config)
            initial_content = [{"type": "text", "text": encoded(request.model_dump(mode="json"))}]
            if not checkpoint.next and request.role == "organizer":
                # Organizing the whole library requires the whole catalog as
                # input. Supply existing evidence mechanically, like an analyst's
                # initial photo; semantic grouping and further inspection remain
                # model decisions. No images or analysis are regenerated here.
                initial_content.append({"type": "text", "text": (
                    "The complete compact library catalog follows. Its pages have already been covered. "
                    "Discover useful contexts across all entries; inspect full evidence/images where needed. "
                    "You do not need to repeat catalog pagination before submitting."
                )})
                for offset in range(0, len(toolkit.allowed()), 100):
                    page = await asyncio.to_thread(toolkit.invoke, "list_photos", {"offset": offset, "limit": 100})
                    initial_content.append({"type": "text", "text": encoded(page)})
            if not checkpoint.next and request.role == "explorer":
                if toolkit.prior_attempt_feedback is not None:
                    initial_content.append(feedback_block(toolkit.prior_attempt_feedback))
                initial_content.append({"type": "text", "text": encoded({"library_status": {
                    "photo_count": self.store.rows("SELECT count(*) AS n FROM photos")[0]["n"],
                    "analyzed_count": self.store.rows("SELECT count(*) AS n FROM analyses")[0]["n"],
                    "instruction": "Use this coverage information to choose retrieval or additional inspection; missing analysis is not evidence of no matches.",
                }})})
            if not checkpoint.next and request.role in ("analyst", "explorer"):
                # The caller already chose the asset. Sending it is transport, not a
                # semantic tool-selection rule, and saves a model round trip.
                photo_id = request.photo_ids[0] if request.role == "analyst" else request.explore.anchor.photo_id
                box = None if request.role == "analyst" else request.explore.anchor.box
                initial_content += await asyncio.to_thread(toolkit.image_block, photo_id, box)
                self.store.event(run_id, "tool", {
                    "name": "initial_photo", "seen": sorted(toolkit.seen),
                    "covered": [], "searched": [],
                })
            initial = (
                None
                if checkpoint.next
                else {
                    "messages": [
                        SystemMessage(content=PROMPTS[request.role]),
                        HumanMessage(content=initial_content),
                    ],
                    "turns": 0,
                    "calls": 0,
                    "spec_version": AGENT_SPEC_VERSION,
                    "review_attempts": 0,
                    "submission_reminded": False,
                    "repair_pending": False,
                    "repair_used": False,
                }
            )
            try:
                await compiled.ainvoke(initial, config=config)
                if toolkit.defer_spaces and toolkit.result is not None:
                    from connected_gallery.domain.models import SpaceProposal
                    reviewed = await self.space_reviewer.review(toolkit, request, toolkit.result)
                    toolkit.defer_spaces = False
                    await asyncio.to_thread(toolkit.submit_space_proposal, SpaceProposal.model_validate(reviewed))
            finally:
                # Checkpoints retain images only while execution needs them.
                await saver.adelete_thread(run_id)
        if toolkit.result is None:
            raise RuntimeError("Agent finished without a valid submitted result")
        return toolkit.result
