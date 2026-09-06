from __future__ import annotations
import asyncio
import json
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
            response = await self.gateway.invoke(state["messages"], toolkit.schemas())
            return {"messages": [response], "turns": state.get("turns", 0) + 1}

        async def tools(state):
            messages = []
            calls = state.get("calls", 0)
            for call in state["messages"][-1].tool_calls:
                calls += 1
                if calls > max_calls:
                    raise RuntimeError("Tool budget exceeded")
                try:
                    result = await asyncio.to_thread(
                        toolkit.invoke, call["name"], call["args"]
                    )
                    content = result if isinstance(result, list) else encoded(result)
                except Exception as e:
                    # Validation errors are useful to the model; infrastructure details are redacted.
                    content = encoded(
                        {
                            "error": str(e)[:300]
                            if isinstance(e, ValueError)
                            else type(e).__name__
                        }
                    )
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
            initial = (
                None
                if checkpoint.next
                else {
                    "messages": [
                        SystemMessage(content=PROMPTS[request.role]),
                        HumanMessage(content=encoded(request.model_dump(mode="json"))),
                    ],
                    "turns": 0,
                    "calls": 0,
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
