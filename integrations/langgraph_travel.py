"""
LangGraph Integration — A2A agents as graph nodes.

Wraps each remote A2A agent as a LangGraph node, using A2A calls
as the edges between them. LangGraph manages state and transitions;
A2A handles inter-agent communication over HTTP.

Usage:
    python integrations/langgraph_travel.py

Requires Flight (5001), Hotel (5002), and Itinerary (5003) agents running.
"""

import asyncio
from typing import Any, TypedDict
from uuid import uuid4

import httpx
from langgraph.graph import StateGraph, END

from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import (
    AgentCard, Message, Part, TextPart, DataPart,
    Role, TaskArtifactUpdateEvent, TaskState, TaskQueryParams,
)


# --- Graph state ---
class TravelState(TypedDict):
    query: str
    flight_results: dict[str, Any]
    hotel_results: dict[str, Any]
    itinerary: dict[str, Any]
    status: str


# --- Helpers ---
async def _call_a2a_agent(
    agent_url: str,
    text: str,
    data: dict | None = None,
) -> dict:
    """
    Send a message to a remote A2A agent and collect its artifacts.
    Returns the first DataPart payload found, or an empty dict.
    """
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        resolver = A2ACardResolver(http_client, agent_url)
        card: AgentCard = await resolver.get_agent_card()

        supports_streaming = bool(
            card.capabilities and card.capabilities.streaming
        )
        config = ClientConfig(
            streaming=supports_streaming,
            polling=not supports_streaming,
        )
        client = await ClientFactory.connect(card, client_config=config)

        parts: list[Part] = [Part(root=TextPart(text=text))]
        if data:
            parts.append(Part(root=DataPart(data=data)))

        message = Message(
            role=Role.user,
            parts=parts,
            message_id=str(uuid4()),
        )

        artifact_data: dict[str, Any] = {}
        final_task = None

        async for event in client.send_message(message):
            if isinstance(event, tuple):
                task, update = event
                final_task = task
                if isinstance(update, TaskArtifactUpdateEvent) and update.artifact:
                    for part in update.artifact.parts:
                        if isinstance(part.root, DataPart):
                            artifact_data = part.root.data

        # Poll until complete for non-streaming agents
        if not supports_streaming and final_task:
            while final_task.status and final_task.status.state in (
                TaskState.submitted, TaskState.working, TaskState.input_required
            ):
                await asyncio.sleep(1.0)
                final_task = await client.get_task(TaskQueryParams(id=final_task.id))

            if final_task.artifacts:
                for artifact in final_task.artifacts:
                    for part in artifact.parts:
                        if isinstance(part.root, DataPart):
                            artifact_data = part.root.data

        return artifact_data


# --- A2A-backed graph nodes ---
async def search_flights(state: TravelState) -> TravelState:
    """LangGraph node: delegates flight search to the A2A Flight Agent."""
    flight_results = await _call_a2a_agent(
        "http://localhost:5001", state["query"]
    )
    return {
        **state,
        "flight_results": flight_results,
        "status": "flights_found",
    }


async def search_hotels(state: TravelState) -> TravelState:
    """LangGraph node: delegates hotel search to the A2A Hotel Agent."""
    hotel_results = await _call_a2a_agent(
        "http://localhost:5002", state["query"]
    )
    return {
        **state,
        "hotel_results": hotel_results,
        "status": "hotels_found",
    }


async def generate_itinerary(state: TravelState) -> TravelState:
    """
    LangGraph node: sends combined flight + hotel artifacts
    to the A2A Itinerary Agent for final plan generation.
    """
    itinerary = await _call_a2a_agent(
        "http://localhost:5003",
        text=f"Generate itinerary for: {state['query']}",
        data={
            "flights": state["flight_results"],
            "hotels": state["hotel_results"],
        },
    )
    return {
        **state,
        "itinerary": itinerary,
        "status": "complete",
    }


# --- Build the graph ---
def build_travel_graph():
    """
    Construct a LangGraph workflow where each node is backed
    by a remote A2A agent. LangGraph owns state and transitions;
    A2A owns inter-agent communication.
    """
    graph = StateGraph(TravelState)

    graph.add_node("search_flights", search_flights)
    graph.add_node("search_hotels", search_hotels)
    graph.add_node("generate_itinerary", generate_itinerary)

    graph.set_entry_point("search_flights")
    graph.add_edge("search_flights", "search_hotels")
    graph.add_edge("search_hotels", "generate_itinerary")
    graph.add_edge("generate_itinerary", END)

    return graph.compile()


# --- Entry point ---
async def run_langgraph_travel_planner():
    """Run the LangGraph-based travel planner over A2A edges."""
    graph = build_travel_graph()

    print("\n" + "=" * 60)
    print("   LANGGRAPH + A2A TRAVEL PLANNER")
    print("=" * 60)
    print("\n  Enter your travel query below.")
    print("  Example: Plan a Tokyo trip, March 15-22, 2 travelers\n")
    query = input("  Your query: ").strip()
    if not query:
        query = "Plan a Tokyo trip, March 15-22, 2 travelers"
        print(f"  (using default: {query})")

    initial_state: TravelState = {
        "query": query,
        "flight_results": {},
        "hotel_results": {},
        "itinerary": {},
        "status": "started",
    }

    print(f"\nRunning graph for: {query}\n")
    final_state = await graph.ainvoke(initial_state)

    W = 72
    sep = "=" * W
    flights = final_state["flight_results"].get("flights", [])
    hotels = final_state["hotel_results"].get("hotels", [])
    daily_plan = final_state["itinerary"].get("daily_plan", {})
    tips = final_state["itinerary"].get("tips", [])

    print(f"\n{sep}")
    print(f"  TRAVEL PLAN — {query}")
    print(sep)

    print(f"\n  FLIGHTS")
    print(f"  {'-'*(W-4)}")
    print(f"  {'Airline':<12} {'Flight':<8} {'Route':<28} {'Price':>7} {'Duration':<10}")
    print(f"  {'-'*12:<12} {'-'*8:<8} {'-'*28:<28} {'-'*7:>7} {'-'*10:<10}")
    for f in flights:
        route = f"{f.get('departure','')[:14]} > {f.get('arrival','')[:11]}"
        print(f"  {f.get('airline',''):<12} {f.get('flight',''):<8} {route:<28} {'$'+str(f.get('price','')):>7} {f.get('duration',''):<10}")

    print(f"\n  HOTELS")
    print(f"  {'-'*(W-4)}")
    print(f"  {'Hotel':<28} {'Location':<18} {'Price':>10} {'Rating':>7}")
    print(f"  {'-'*28:<28} {'-'*18:<18} {'-'*10:>10} {'-'*7:>7}")
    for h in hotels:
        print(f"  {h.get('name','')[:27]:<28} {h.get('location','')[:17]:<18} {'$'+str(h.get('price_per_night',''))+'/n':>10} {h.get('rating',''):>7}")

    print(f"\n  ITINERARY")
    print(f"  {'-'*(W-4)}")
    for day_key in sorted(daily_plan.keys(), key=lambda x: int(x.split()[-1])):
        day = daily_plan[day_key]
        print(f"\n  {day_key}: {day.get('title', '')}")
        for a in day.get("activities", []):
            print(f"    - {a}")

    if tips:
        print(f"\n  TIPS")
        print(f"  {'-'*(W-4)}")
        for t in tips:
            print(f"    * {t}")

    print(f"\n{sep}")
    print(f"  Plan complete!")
    print(sep)

    return final_state


if __name__ == "__main__":
    asyncio.run(run_langgraph_travel_planner())
