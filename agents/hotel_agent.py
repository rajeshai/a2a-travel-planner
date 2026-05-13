"""
Hotel Search Agent — A2A-compliant server (non-streaming).

Searches for hotels and returns structured results as artifacts.
Does not support SSE streaming — returns complete results in
a single response.

Usage:
    python agents/hotel_agent.py

Runs on http://localhost:5002
"""

import asyncio
import json
import re
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import uvicorn

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.jsonrpc.starlette_app import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Task, TaskState, TaskStatus, Artifact,
    Message, Part, TextPart, DataPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent,
)

# Add parent directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.mock_apis import MOCK_HOTELS


class HotelAgentExecutor(AgentExecutor):
    """
    A2A-compliant Hotel Search Agent.
    Searches for hotel accommodations and returns structured
    results as a single artifact (no streaming).
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Main execution method called by the A2A server
        when a task is received.
        """
        task_id = context.task_id
        context_id = context.context_id

        # Parse query
        query = self._extract_query(context)

        # Status: searching
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=Message(
                        role="agent",
                        parts=[Part(root=TextPart(
                            text=f"Searching hotels in {query['city']}..."
                        ))],
                        message_id=str(uuid4()),
                    )
                )
            )
        )

        # Simulate API latency
        await asyncio.sleep(1.0)

        # Filter hotels
        results = MOCK_HOTELS.copy()

        if query.get("max_price_per_night") is not None:
            results = [
                h for h in results
                if h["price_per_night"] <= query["max_price_per_night"]
            ]

        if query.get("min_rating") is not None:
            results = [
                h for h in results
                if h["rating"] >= query["min_rating"]
            ]

        # Sort by rating descending
        results = sorted(results, key=lambda h: h["rating"], reverse=True)

        # Produce artifact with top 3 results
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=str(uuid4()),
                    name="hotel_options",
                    parts=[Part(root=DataPart(data={
                        "hotels": results[:3],
                        "search_metadata": {
                            "city": query["city"],
                            "total_found": len(MOCK_HOTELS),
                            "filtered_count": len(results),
                            "guests": query.get("guests", 2),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                    }))]
                )
            )
        )

        # Mark completed
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.completed,
                    message=Message(
                        role="agent",
                        parts=[Part(root=TextPart(
                            text=f"Hotel search complete. "
                                 f"{len(results)} options found."
                        ))],
                        message_id=str(uuid4()),
                    )
                )
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle task cancellation."""
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=True,
                status=TaskStatus(state=TaskState.canceled),
            )
        )

    def _extract_query(self, context: RequestContext) -> dict:
        """Parse city, price, and rating from the task message."""
        text = context.get_user_input()

        # Simple extraction — production agents would use NLP/LLM
        query = {
            "city": "Tokyo",
            "max_price_per_night": None,
            "min_rating": None,
            "guests": 2
        }

        text_lower = text.lower()

        # Extract guest count
        guest_match = re.search(r"(\d+)\s*(?:guest|traveler|people|person)", text_lower)
        if guest_match:
            query["guests"] = int(guest_match.group(1))

        return query


def start_hotel_agent(host: str = "0.0.0.0", port: int = 5002):
    """Launch the Hotel Agent A2A server."""
    card_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "agent_cards", "hotel_card.json"
    )

    with open(card_path) as f:
        card_data = json.load(f)

    agent_card = AgentCard(
        name=card_data["name"],
        description=card_data["description"],
        url=card_data["url"],
        version=card_data["version"],
        capabilities=AgentCapabilities(
            streaming=card_data["capabilities"]["streaming"],
            push_notifications=card_data["capabilities"].get("pushNotifications", False),
        ),
        skills=[
            AgentSkill(**skill) for skill in card_data["skills"]
        ],
        default_input_modes=card_data.get("defaultInputModes", ["text"]),
        default_output_modes=card_data.get("defaultOutputModes", ["data"]),
    )

    executor = HotelAgentExecutor()
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    print(f"Hotel Agent running at http://{host}:{port}")
    print(f"Agent Card: http://{host}:{port}/.well-known/agent.json")

    uvicorn.run(app.build(), host=host, port=port)


if __name__ == "__main__":
    start_hotel_agent()
