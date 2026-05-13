"""
CrewAI-to-A2A Bridge — Expose a CrewAI crew as an A2A-compliant server.

Wraps a CrewAI crew as an A2A-discoverable agent, making it callable
by any other A2A agent — even ones built in completely different
frameworks. The outside world sees an agent with a `crew_itinerary`
skill; CrewAI is an implementation detail.

Usage:
    python integrations/crewai_a2a_bridge.py

Runs on http://localhost:5004
"""

from dotenv import load_dotenv
load_dotenv()

import asyncio
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
    TaskState, TaskStatus, Artifact,
    Message, Part, TextPart, DataPart,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent,
)

# Add parent directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class CrewAIBridgeExecutor(AgentExecutor):
    """
    Wraps a CrewAI Crew as an A2A-compliant AgentExecutor.

    Incoming A2A tasks are translated into a CrewAI task chain,
    executed by the crew, and results are returned as A2A artifacts.
    """

    def __init__(self):
        from crewai import Agent, LLM

        gemini_llm = LLM(
            model="gemini/gemini-2.0-flash-lite",
            api_key=os.environ.get("GEMINI_API_KEY"),
        )

        self.researcher = Agent(
            role="Travel Researcher",
            goal="Research the best activities and restaurants "
                 "at the travel destination",
            backstory="You are an experienced travel blogger who "
                      "has visited over 50 countries.",
            verbose=False,
            llm=gemini_llm,
        )
        self.planner = Agent(
            role="Itinerary Planner",
            goal="Create a detailed day-by-day travel itinerary",
            backstory="You are a professional travel planner who "
                      "creates custom luxury itineraries.",
            verbose=False,
            llm=gemini_llm,
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute a CrewAI workflow in response to an A2A task."""
        from crewai import Task as CrewTask, Crew, Process

        task_id = context.task_id
        context_id = context.context_id

        # Extract the user's query from the incoming message
        query = self._extract_query(context)

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
                            text="Crew assembled. Researching destination..."
                        ))],
                        message_id=str(uuid4()),
                    ),
                ),
            )
        )

        # --- Phase 2: Build and run the CrewAI crew ---
        research_task = CrewTask(
            description=f"Research top activities, restaurants, "
                        f"and cultural tips for: {query}",
            expected_output="A detailed list of recommended activities "
                            "and restaurants with descriptions.",
            agent=self.researcher,
        )
        planning_task = CrewTask(
            description=f"Create a day-by-day itinerary for: {query}. "
                        f"Use the research results to fill in activities.",
            expected_output="A complete day-by-day itinerary in "
                            "structured format.",
            agent=self.planner,
        )
        crew = Crew(
            agents=[self.researcher, self.planner],
            tasks=[research_task, planning_task],
            process=Process.sequential,
            verbose=False,
        )

        # CrewAI's kickoff is synchronous; offload to a thread so we don't
        # block the async event loop serving other A2A requests.
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, crew.kickoff)
        except Exception as e:
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task_id,
                    context_id=context_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            role="agent",
                            parts=[Part(root=TextPart(text=f"CrewAI error: {e}"))],
                            message_id=str(uuid4()),
                        ),
                    ),
                )
            )
            return

        # --- Phase 3: Emit the result as an A2A artifact ---
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=Artifact(
                    artifact_id=str(uuid4()),
                    name="crew_itinerary",
                    parts=[Part(root=DataPart(data={
                        "itinerary": str(result),
                        "generated_by": "CrewAI Travel Crew",
                        "agents_used": ["Travel Researcher", "Itinerary Planner"],
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    }))],
                ),
            )
        )

        # --- Phase 4: Complete ---
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
                            text="Crew itinerary complete."
                        ))],
                        message_id=str(uuid4()),
                    ),
                ),
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

    def _extract_query(self, context: RequestContext) -> str:
        """Extract the text query from the incoming task message."""
        return context.get_user_input() or "Plan a trip to Tokyo"


def start_crewai_a2a_server(host: str = "0.0.0.0", port: int = 5004):
    """Launch the CrewAI-backed A2A agent."""
    agent_card = AgentCard(
        name="CrewAI Travel Crew",
        description=(
            "A multi-agent crew that researches destinations and generates "
            "detailed travel itineraries. Implemented with CrewAI, exposed via A2A."
        ),
        url=f"http://localhost:{port}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        skills=[
            AgentSkill(
                id="crew_itinerary",
                name="Generate Crew Itinerary",
                description="Research and plan a complete travel itinerary "
                            "using a collaborative agent crew.",
                tags=["itinerary", "travel", "crewai"],
                input_modes=["text"],
                output_modes=["data"],
            )
        ],
        default_input_modes=["text"],
        default_output_modes=["data"],
    )

    executor = CrewAIBridgeExecutor()
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    print(f"CrewAI A2A Agent running at http://{host}:{port}")
    print(f"Agent Card: http://{host}:{port}/.well-known/agent.json")

    uvicorn.run(app.build(), host=host, port=port)


if __name__ == "__main__":
    start_crewai_a2a_server()
