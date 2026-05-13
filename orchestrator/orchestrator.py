"""
Travel Planner Orchestrator — Discovers and coordinates
Flight, Hotel, and Itinerary agents via A2A protocol.

Handles:
- Agent discovery via Agent Cards
- Parallel task dispatch (flight + hotel simultaneously)
- Artifact collection and forwarding
- Streaming and polling-based task monitoring

Usage:
    Imported by run_demo.py — not run directly.
"""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.client.helpers import create_text_message_object
from a2a.types import (
    AgentCard, Task, TaskState, Message, Part,
    TextPart, DataPart, TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent, Role, TaskQueryParams
)

import httpx


class TravelPlannerOrchestrator:
    """
    Orchestrator agent that discovers and coordinates Flight, Hotel,
    and Itinerary agents to build a complete travel plan.
    """

    def __init__(self, agent_urls: list[str]):
        """
        Initialize with a list of agent base URLs.
        The orchestrator will discover each agent's capabilities
        via their Agent Cards.
        """
        self.agent_urls = agent_urls
        self.agents: dict[str, dict] = {}
        self.cards: dict[str, AgentCard] = {}

    async def discover_agents(self) -> None:
        """
        Fetch Agent Cards from all registered URLs.
        Maps agent skills to their endpoints for task routing.
        """
        async with httpx.AsyncClient() as http_client:
            for url in self.agent_urls:
                try:
                    resolver = A2ACardResolver(http_client, url)
                    card = await resolver.get_agent_card()
                    agent_name = card.name

                    skill_ids = [s.id for s in card.skills]
                    supports_streaming = (
                        card.capabilities.streaming
                        if card.capabilities else False
                    )

                    self.agents[agent_name] = {
                        "url": url,
                        "card": card,
                        "skills": skill_ids,
                        "streaming": supports_streaming,
                    }
                    self.cards[agent_name] = card

                    print(
                        f"Discovered: {agent_name} at {url} "
                        f"(skills: {skill_ids}, "
                        f"streaming: {supports_streaming})"
                    )

                except Exception as e:
                    print(f"Failed to discover agent at {url}: {e}")

    def find_agent_by_skill(self, skill_id: str) -> str | None:
        """Find the first agent that supports a given skill."""
        for name, info in self.agents.items():
            if skill_id in info["skills"]:
                return name
        return None

    async def run_travel_plan(self, user_query: str) -> dict:
        """
        Execute the full travel planning workflow:
        1. Flight search (with streaming)
        2. Hotel search (parallel with flight)
        3. Itinerary generation (after both complete)
        """
        print(f"\n{'='*60}")
        print(f"Travel Planner — {user_query}")
        print(f"{'='*60}\n")

        # --- Step 1 & 2: Parallel flight + hotel search ---
        flight_agent = self.find_agent_by_skill("search_flights")
        hotel_agent = self.find_agent_by_skill("search_hotels")

        if not flight_agent or not hotel_agent:
            raise RuntimeError(
                "Required agents not found. "
                "Ensure Flight and Hotel agents are running."
            )

        print("Dispatching parallel searches...")
        print(f"  -> {flight_agent}: searching flights")
        print(f"  -> {hotel_agent}: searching hotels\n")

        # Run both in parallel
        flight_result, hotel_result = await asyncio.gather(
            self._send_message_to_agent(flight_agent, user_query),
            self._send_message_to_agent(hotel_agent, user_query),
        )

        # Extract artifacts
        flight_artifacts = flight_result.get("artifacts", [])
        hotel_artifacts = hotel_result.get("artifacts", [])

        print(f"\nFlight search: {len(flight_artifacts)} artifact(s)")
        print(f"Hotel search: {len(hotel_artifacts)} artifact(s)")

        # --- Step 3: Generate itinerary from combined artifacts ---
        itinerary_agent = self.find_agent_by_skill("generate_itinerary")

        if not itinerary_agent:
            # Try CrewAI skill
            itinerary_agent = self.find_agent_by_skill("crew_itinerary")

        if not itinerary_agent:
            raise RuntimeError("Itinerary agent not found.")

        print(f"\n  -> {itinerary_agent}: generating itinerary...\n")

        # Build a message with both text and data parts
        itinerary_result = await self._send_message_to_agent(
            itinerary_agent,
            f"Generate a travel itinerary for: {user_query}",
            data={
                "flights": flight_artifacts,
                "hotels": hotel_artifacts,
                "traveler_preferences": {
                    "trip_type": "leisure",
                    "pace": "moderate"
                }
            }
        )

        # --- Combine everything into the final plan ---
        final_plan = {
            "query": user_query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "flights": flight_artifacts,
            "hotels": hotel_artifacts,
            "itinerary": itinerary_result.get("artifacts", []),
            "status": "complete"
        }

        return final_plan

    async def _send_message_to_agent(
        self, agent_name: str, text: str, data: dict | None = None
    ) -> dict:
        """Send a message to an agent and collect results."""
        card = self.cards[agent_name]
        supports_streaming = self.agents[agent_name]["streaming"]

        config = ClientConfig(
            streaming=supports_streaming,
            polling=not supports_streaming,
        )

        client = await ClientFactory.connect(card, client_config=config)

        # Build message parts
        parts = [Part(root=TextPart(text=text))]
        if data:
            parts.append(Part(root=DataPart(data=data)))

        message = Message(
            role=Role.user,
            parts=parts,
            message_id=str(uuid4()),
        )

        artifacts = []
        final_task = None

        async for event in client.send_message(message):
            if isinstance(event, Message):
                # Direct message response
                print(f"  [{agent_name}] message response received")
                continue

            # event is a tuple: (Task, UpdateEvent | None)
            task, update = event

            if update is None:
                # Initial task object or polling result
                final_task = task
                state = task.status.state if task.status else "unknown"
                print(f"  [{agent_name}] ({state}) polling...")
                continue

            if isinstance(update, TaskStatusUpdateEvent):
                state = update.status.state if update.status else "unknown"
                msg_text = ""
                if (
                    update.status
                    and update.status.message
                    and update.status.message.parts
                ):
                    inner = update.status.message.parts[0].root
                    if isinstance(inner, TextPart):
                        msg_text = inner.text
                print(f"  [{agent_name}] ({state}) {msg_text}")
                final_task = task

            elif isinstance(update, TaskArtifactUpdateEvent):
                if update.artifact:
                    artifact_data = {}
                    for part in update.artifact.parts:
                        inner = part.root
                        if isinstance(inner, DataPart):
                            artifact_data = inner.data
                    artifacts.append(artifact_data)

                final_task = task

        if config.polling and final_task:
            while final_task.status and final_task.status.state in (TaskState.submitted, TaskState.working, TaskState.input_required):
                await asyncio.sleep(1.0)
                final_task = await client.get_task(TaskQueryParams(id=final_task.id))
                state = final_task.status.state if final_task.status else "unknown"
                print(f"  [{agent_name}] ({state}) polling...")


        # Also check task artifacts if present
        if final_task and final_task.artifacts:
            for art in final_task.artifacts:
                for part in art.parts:
                    inner = part.root
                    if isinstance(inner, DataPart) and inner.data not in artifacts:
                        artifacts.append(inner.data)

        return {"task": final_task, "artifacts": artifacts}
