"""
Itinerary Generator Agent — A2A-compliant server with SSE streaming.

Combines flight and hotel data with destination research to produce
a complete day-by-day travel itinerary. Accepts data artifacts from
upstream agents (Flight, Hotel) as input.

Usage:
    python agents/itinerary_agent.py

Runs on http://localhost:5003
"""

import asyncio
import json
import os
import re
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
    TaskState, TaskStatus, Artifact,
    Message, Part, TextPart, DataPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent,
)

# Add parent directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.mock_apis import TOKYO_ACTIVITIES


class ItineraryAgentExecutor(AgentExecutor):
    """
    A2A-compliant Itinerary Generator with SSE streaming.
    Combines flight and hotel artifacts from upstream agents
    to produce a complete day-by-day travel plan.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Main execution method. Accepts text queries and/or data
        artifacts from flight and hotel agents.
        """
        task_id = context.task_id
        context_id = context.context_id

        # Extract input data (text query + any data artifacts)
        query_text, input_data = self._extract_inputs(context)

        # --- Phase 1: Acknowledge ---
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
                            text="Building day-by-day itinerary..."
                        ))],
                        message_id=str(uuid4()),
                    )
                )
            )
        )

        await asyncio.sleep(1.5)

        # --- Phase 2: Process flight and hotel data ---
        flights = input_data.get("flights", [])
        hotels = input_data.get("hotels", [])

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
                            text="Adding restaurant and activity suggestions..."
                        ))],
                        message_id=str(uuid4()),
                    )
                )
            )
        )

        await asyncio.sleep(1.0)

        # --- Phase 3: Build the itinerary ---
        # Parse number of days from query (e.g. "3 days", "March 15-22" = 7 days)
        num_days = 7
        days_match = re.search(r'(\d+)\s*day', query_text, re.IGNORECASE)
        date_match = re.search(r'(\w+ \d+)-(\d+)', query_text)
        if days_match:
            num_days = min(int(days_match.group(1)), 7)
        elif date_match:
            num_days = min(int(date_match.group(2)) - int(date_match.group(1).split()[-1]) + 1, 7)

        all_days = list(TOKYO_ACTIVITIES.items())
        daily_plan = {k: v for k, v in all_days[:num_days]}

        itinerary = {
            "destination": "Tokyo, Japan",
            "duration": f"{num_days} days",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "travel_info": {
                "flights": flights if flights else "No flight data provided",
                "hotels": hotels if hotels else "No hotel data provided"
            },
            "daily_plan": daily_plan,
            "tips": [
                "Get a Suica/Pasmo card for easy transit",
                "Download Google Translate with Japanese offline pack",
                "Carry cash — many small restaurants don't accept cards",
                "Buy a 7-day Japan Rail Pass if planning day trips"
            ]
        }

        # --- Phase 4: Produce artifact ---
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=str(uuid4()),
                    name="travel_itinerary",
                    parts=[Part(root=DataPart(data=itinerary))]
                )
            )
        )

        # --- Phase 5: Complete ---
        total_activities = sum(
            len(day["activities"])
            for day in daily_plan.values()
        )

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
                            text=f"Itinerary ready — {num_days} days, "
                                 f"{total_activities} activities."
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

    def _extract_inputs(self, context: RequestContext) -> tuple[str, dict]:
        """
        Extract both text queries and structured data from the task.
        Returns (query_text, input_data_dict).
        """
        query_text = ""
        input_data = {}

        if context.message:
            for part in context.message.parts:
                inner = part.root
                if isinstance(inner, TextPart):
                    query_text = inner.text
                elif isinstance(inner, DataPart):
                    input_data = inner.data

        return query_text, input_data


def start_itinerary_agent(host: str = "0.0.0.0", port: int = 5003):
    """Launch the Itinerary Agent A2A server."""
    card_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "agent_cards", "itinerary_card.json"
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
        default_input_modes=card_data.get("defaultInputModes", ["data"]),
        default_output_modes=card_data.get("defaultOutputModes", ["text", "data"]),
    )

    executor = ItineraryAgentExecutor()
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    print(f"Itinerary Agent running at http://{host}:{port}")
    print(f"Agent Card: http://{host}:{port}/.well-known/agent.json")

    uvicorn.run(app.build(), host=host, port=port)


if __name__ == "__main__":
    start_itinerary_agent()
