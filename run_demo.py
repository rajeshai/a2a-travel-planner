"""
Multi-Agent Travel Planner Demo -- Entry Point

Discovers Flight, Hotel, and Itinerary agents via A2A protocol,
asks the user for their travel query, runs the orchestrated
workflow, and prints a human-readable travel plan.

Usage:
    1. Start agents in separate terminals:
        python agents/flight_agent.py      # Terminal 1 (port 5001)
        python agents/hotel_agent.py       # Terminal 2 (port 5002)
        python agents/itinerary_agent.py   # Terminal 3 (port 5003)

    2. Run the demo:
        python run_demo.py                 # Terminal 4
"""

import argparse
import asyncio
import json
import sys

from orchestrator.orchestrator import TravelPlannerOrchestrator


def print_travel_plan(plan: dict) -> None:
    """Print the travel plan as clean ASCII tables."""
    W = 72
    sep = "=" * W

    print(f"\n{sep}")
    print(f"  TRAVEL PLAN")
    print(f"  {plan.get('query', 'N/A')}")
    print(sep)

    # --- Extract data ---
    flight_list, flight_meta = [], {}
    for art in plan.get("flights", []):
        if "flights" in art:
            flight_list = art.get("flights", [])
            flight_meta = art.get("search_metadata", {})

    hotel_list = []
    for art in plan.get("hotels", []):
        if "hotels" in art:
            hotel_list = art.get("hotels", [])

    daily_plan, tips = {}, []
    for art in plan.get("itinerary", []):
        if "daily_plan" in art:
            daily_plan = art.get("daily_plan", {})
            tips = art.get("tips", [])

    # --- Flights Table ---
    print(f"\n  FLIGHTS ({flight_meta.get('filtered_count','?')}/{flight_meta.get('total_found','?')} matched)")
    print(f"  {'-'*(W-4)}")
    print(f"  {'Airline':<12} {'Flight':<8} {'Route':<28} {'Price':>7} {'Duration':<10}")
    print(f"  {'-'*12:<12} {'-'*8:<8} {'-'*28:<28} {'-'*7:>7} {'-'*10:<10}")
    for f in flight_list:
        route = f"{f.get('departure','')[:14]} > {f.get('arrival','')[:11]}"
        print(f"  {f.get('airline',''):<12} {f.get('flight',''):<8} {route:<28} {'$'+str(f.get('price','')):>7} {f.get('duration',''):<10}")
    if not flight_list:
        print(f"  {'(no flights matched your budget)':^{W-4}}")

    # --- Hotels Table ---
    print(f"\n  HOTELS")
    print(f"  {'-'*(W-4)}")
    print(f"  {'Hotel':<28} {'Location':<18} {'Price':>10} {'Rating':>7}")
    print(f"  {'-'*28:<28} {'-'*18:<18} {'-'*10:>10} {'-'*7:>7}")
    for h in hotel_list:
        name = h.get('name','')[:27]
        loc = h.get('location','')[:17]
        price = f"${h.get('price_per_night','')}/n"
        print(f"  {name:<28} {loc:<18} {price:>10} {h.get('rating',''):>7}")
    if not hotel_list:
        print(f"  {'(no hotels found)':^{W-4}}")

    # --- Itinerary ---
    print(f"\n  ITINERARY")
    print(f"  {'-'*(W-4)}")
    for day_key in sorted(daily_plan.keys(), key=lambda x: int(x.split()[-1])):
        day = daily_plan[day_key]
        print(f"\n  {day_key}: {day.get('title', '')}")
        for a in day.get("activities", []):
            print(f"    - {a}")

    # --- Tips ---
    if tips:
        print(f"\n  TIPS")
        print(f"  {'-'*(W-4)}")
        for t in tips:
            print(f"    * {t}")

    print(f"\n{sep}")
    print(f"  Plan complete!")
    print(sep)


async def main(use_crewai: bool = False):
    # Agent URLs
    itinerary_port = 5004 if use_crewai else 5003
    agent_urls = [
        "http://localhost:5001",  # Flight Agent
        "http://localhost:5002",  # Hotel Agent
        f"http://localhost:{itinerary_port}",  # Itinerary Agent
    ]

    # Discover agents
    print("\nDiscovering agents...\n")
    planner = TravelPlannerOrchestrator(agent_urls)
    await planner.discover_agents()

    # Verify all required agents
    for skill in ["search_flights", "search_hotels"]:
        if not planner.find_agent_by_skill(skill):
            print(f"\nERROR: No agent found with skill '{skill}'.")
            print("Make sure all agent servers are running.")
            sys.exit(1)

    itinerary_skill = "crew_itinerary" if use_crewai else "generate_itinerary"
    if not planner.find_agent_by_skill(itinerary_skill):
        print("\nERROR: No itinerary agent found.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("   MULTI-AGENT TRAVEL PLANNER")
    print(f"{'='*60}\n")

    # Ask for user input
    print("  Enter your travel query below.")
    print("  Example: Plan a Tokyo trip, March 15-22, 2 travelers, budget under $900\n")
    query = input("  Your query: ").strip()

    if not query:
        print("  No query entered. Using default.")
        query = "Plan a Tokyo trip, March 15-22, 2 travelers, budget under $900"

    print()

    # Run the workflow
    plan = await planner.run_travel_plan(query)

    # Print human-readable output
    print_travel_plan(plan)

    # Also save raw JSON
    output_path = "travel_plan_output.json"
    with open(output_path, "w") as f:
        json.dump(plan, f, indent=2, default=str)
    print(f"\n  (Raw JSON also saved to {output_path})\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--crewai", action="store_true", help="Use CrewAI bridge on port 5004")
    args = parser.parse_args()
    asyncio.run(main(use_crewai=args.crewai))
