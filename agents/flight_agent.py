"""
Flight Search Agent — A2A-compliant server with SSE streaming.

Searches for flights and pushes real-time progress updates
to subscribing clients via Server-Sent Events.

Usage:
    python agents/flight_agent.py

Runs on http://localhost:5001
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
from utils.mock_apis import MOCK_FLIGHTS


class FlightAgentExecutor(AgentExecutor):
    """
    A2A-compliant Flight Search Agent with SSE streaming support.
    Pushes real-time progress updates as it searches and filters
    flight options.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Main execution method called by the A2A server
        when a task is received.
        """
        task_id = context.task_id
        context_id = context.context_id

        # Parse the user's query from the incoming message
        query = self._extract_query(context)

        # --- Phase 1: Acknowledge and begin searching ---
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
                            text=f"Searching flights to {query['destination']}..."
                        ))],
                        message_id=str(uuid4()),
                    )
                )
            )
        )

        # Simulate API latency for realistic streaming demo
        await asyncio.sleep(1.5)

        # --- Phase 2: Return initial results count ---
        matching = [
            f for f in MOCK_FLIGHTS
            if query.get("max_price") is None
            or f["price"] <= query["max_price"]
        ]

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
                            text=f"Found {len(MOCK_FLIGHTS)} flights. "
                                 f"Filtering by preferences..."
                        ))],
                        message_id=str(uuid4()),
                    )
                )
            )
        )

        await asyncio.sleep(1.0)

        # --- Phase 3: Stream filtered results ---
        sorted_flights = sorted(matching, key=lambda f: f["price"])

        if sorted_flights:
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
                                text=f"Top option: {sorted_flights[0]['airline']} "
                                     f"{sorted_flights[0]['flight']} — "
                                     f"${sorted_flights[0]['price']} nonstop"
                            ))],
                            message_id=str(uuid4()),
                        )
                    )
                )
            )

        await asyncio.sleep(0.5)

        # --- Phase 4: Produce final artifact ---
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=str(uuid4()),
                    name="flight_options",
                    parts=[Part(root=DataPart(data={
                        "flights": sorted_flights[:3],
                        "search_metadata": {
                            "destination": query["destination"],
                            "total_found": len(MOCK_FLIGHTS),
                            "filtered_count": len(sorted_flights),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                    }))]
                )
            )
        )

        # --- Phase 5: Mark task as completed ---
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
                            text=f"Flight search complete. "
                                 f"{len(sorted_flights)} options within budget."
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
        """Parse destination and preferences from the task message."""
        text = context.get_user_input()

        # Simple extraction — production agents would use NLP/LLM
        query = {"destination": "Tokyo", "max_price": None}
        text_lower = text.lower()

        if "budget" in text_lower or "under" in text_lower:
            match = re.search(r"\$(\d+)", text)
            if match:
                query["max_price"] = int(match.group(1))

        return query


def start_flight_agent(host: str = "0.0.0.0", port: int = 5001):
    """Launch the Flight Agent A2A server."""
    card_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "agent_cards", "flight_card.json"
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

    executor = FlightAgentExecutor()
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    print(f"Flight Agent running at http://{host}:{port}")
    print(f"Agent Card: http://{host}:{port}/.well-known/agent.json")

    uvicorn.run(app.build(), host=host, port=port)


if __name__ == "__main__":
    start_flight_agent()
