from __future__ import annotations
import asyncio
import json
import time
from typing import Annotated, TypedDict
import aiosqlite
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from connected_gallery.agent_specs.prompts import PROMPTS
from connected_gallery.gallery_tools.registry import GalleryTools
from connected_gallery.adapters.store import encoded


class State(TypedDict):
    messages: Annotated[list, add_messages]
    turns: int
    calls: int
    spec_version: int


class GraphAgentRunner:
    def __init__(self, store, models, gateway):
        self.store = store
        self.models = models
        self.gateway = gateway

    async def execute(self, run_id, request):
        toolkit = GalleryTools(self.store, self.models, request, run_id)
        for row in self.store.rows(
            "SELECT data FROM events WHERE run_id=? AND kind='tool'", (run_id,)
        ):
            data = json.loads(row["data"])
            toolkit.seen.update(data.get("seen", []))
            toolkit.covered.update(data.get("covered", []))
            toolkit.searched.update(data.get("searched", []))
        turns = {"analyst": 4, "explorer": 6, "organizer": 30}[request.role]
        max_calls = {"analyst": 12, "explorer": 12, "organizer": 100}[request.role]

        async def model(state):
            if state.get("turns", 0) >= turns:
                raise RuntimeError("Model turn budget exceeded")
            self.store.event(
                run_id,
                "progress",
                {
                    "message": "사진의 연결을 살펴보고 있어요",
                    "turn": state.get("turns", 0) + 1,
                },
            )
            remaining = turns - state.get("turns", 0)
            finalizing = remaining == 1 or state.get("calls", 0) >= max_calls - 1
            budget = SystemMessage(content=(
                f"Execution budget: {remaining} model responses and "
                f"{max_calls - state.get('calls', 0)} tool calls remain. "
                + ("This is the final response: submit your evidence-grounded result now. "
                   "Record missing evidence as uncertainty; do not invent observations."
                   if finalizing else
                   "Reserve the last response for submission. Batch independent tool calls, "
                   "and submit as soon as enough evidence is available.")
            ))
            schemas = toolkit.schemas()
            if finalizing:
                schemas = [s for s in schemas if s["name"].startswith("submit_")]
            started = time.monotonic()
            response = await self.gateway.invoke(
                [state["messages"][0], budget, *state["messages"][1:]], schemas
            )
            self.store.event(run_id, "model_timing", {
                "turn": state.get("turns", 0) + 1,
                "seconds": round(time.monotonic() - started, 3),
                "finalizing": finalizing,
            })
            return {"messages": [response], "turns": state.get("turns", 0) + 1}

        async def tools(state):
            messages = []
            calls = state.get("calls", 0)
            for call in state["messages"][-1].tool_calls:
                if calls >= max_calls - 1 and not call["name"].startswith("submit_"):
                    messages.append(ToolMessage(
                        content=encoded({"error": "Tool budget reserved for submission. Submit current evidence now."}),
                        tool_call_id=call["id"],
                    ))
                    continue
                calls += 1
                if calls > max_calls:
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
                    # Validation errors are useful to the model; infrastructure details are redacted.
                    content = encoded(
                        {
                            "error": str(e)[:300]
                            if isinstance(e, ValueError)
                            else type(e).__name__
                        }
                    )
                self.store.event(run_id, "tool_timing", {
                    "name": call["name"],
                    "seconds": round(time.monotonic() - started, 3),
                    "error": error,
                })
                messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
            return {"messages": messages, "calls": calls}

        def after_model(state):
            return "tools" if state["messages"][-1].tool_calls else END

        def after_tools(state):
            return (
                END
                if toolkit.result and toolkit.result.get("complete", True)
                else "model"
            )

        graph = StateGraph(State)
        graph.add_node("model", model)
        graph.add_node("tools", tools)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", after_model)
        graph.add_conditional_edges("tools", after_tools)
        async with aiosqlite.connect(
            self.store.root / "checkpoints.sqlite"
        ) as connection:
            saver = AsyncSqliteSaver(connection)
            compiled = graph.compile(checkpointer=saver)
            config = {
                "configurable": {"thread_id": run_id},
                "recursion_limit": 2 * turns + 5,
            }
            checkpoint = await compiled.aget_state(config)
            if checkpoint.next and checkpoint.values.get("spec_version") != 2:
                # Old prompts/budgets must not resume halfway through the new graph.
                # Stored model artifacts survive; only this run's conversation resets.
                await saver.adelete_thread(run_id)
                checkpoint = await compiled.aget_state(config)
            initial_content = [{"type": "text", "text": encoded(request.model_dump(mode="json"))}]
            if not checkpoint.next and request.role == "analyst":
                # The caller already chose the asset. Sending it is transport, not a
                # semantic tool-selection rule, and saves a model round trip.
                initial_content += await asyncio.to_thread(toolkit.image_block, request.photo_ids[0])
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
                    "spec_version": 2,
                }
            )
            try:
                await compiled.ainvoke(initial, config=config)
            finally:
                # Checkpoints retain images only while execution needs them.
                await saver.adelete_thread(run_id)
        if toolkit.result is None:
            raise RuntimeError("Agent finished without a valid submitted result")
        return toolkit.result
