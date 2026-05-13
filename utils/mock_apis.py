"""
Mock flight and hotel APIs for local testing.
Replace these with real API calls (e.g., Amadeus, Booking.com)
for production use.
"""

import asyncio
import random
from datetime import datetime, timedelta


MOCK_FLIGHTS = [
    {
        "airline": "ANA", "flight": "NH101",
        "departure": "SFO 10:30 AM", "arrival": "NRT 2:30 PM+1",
        "price": 847, "stops": 0, "duration": "11h 00m"
    },
    {
        "airline": "JAL", "flight": "JL001",
        "departure": "SFO 1:15 PM", "arrival": "HND 5:25 PM+1",
        "price": 923, "stops": 0, "duration": "11h 10m"
    },
    {
        "airline": "United", "flight": "UA837",
        "departure": "SFO 11:00 AM", "arrival": "NRT 3:20 PM+1",
        "price": 756, "stops": 0, "duration": "11h 20m"
    },
    {
        "airline": "Delta", "flight": "DL275",
        "departure": "SFO 8:45 AM", "arrival": "HND 1:05 PM+1",
        "price": 1102, "stops": 1, "duration": "14h 20m"
    },
    {
        "airline": "ANA", "flight": "NH107",
        "departure": "SFO 6:00 PM", "arrival": "NRT 10:00 PM+1",
        "price": 689, "stops": 0, "duration": "11h 00m"
    },
]

TOKYO_ACTIVITIES = {
    "Day 1": {
        "title": "Arrival & Shinjuku Exploration",
        "activities": [
            "Arrive at Narita/Haneda Airport",
            "Check into hotel",
            "Explore Shinjuku Gyoen National Garden",
            "Dinner at Omoide Yokocho (Memory Lane)"
        ]
    },
    "Day 2": {
        "title": "Temples & Traditional Culture",
        "activities": [
            "Morning visit to Senso-ji Temple in Asakusa",
            "Explore Nakamise Shopping Street",
            "Lunch: authentic ramen in Asakusa",
            "Afternoon at Meiji Shrine",
            "Evening in Harajuku — Takeshita Street"
        ]
    },
    "Day 3": {
        "title": "Modern Tokyo & Tech",
        "activities": [
            "TeamLab Borderless digital art museum",
            "Lunch in Odaiba waterfront",
            "Akihabara Electric Town exploration",
            "Dinner at an izakaya in Yurakucho"
        ]
    },
    "Day 4": {
        "title": "Day Trip — Nikko or Kamakura",
        "activities": [
            "Train to Kamakura (1 hour from Tokyo)",
            "Visit the Great Buddha (Kotoku-in)",
            "Hike the Daibutsu trail",
            "Lunch at a seaside restaurant",
            "Return to Tokyo in the evening"
        ]
    },
    "Day 5": {
        "title": "Food & Markets",
        "activities": [
            "Early morning at Tsukiji Outer Market",
            "Sushi breakfast at the market",
            "Explore Ginza shopping district",
            "Cooking class: learn to make gyoza",
            "Evening stroll along Sumida River"
        ]
    },
    "Day 6": {
        "title": "Nature & Relaxation",
        "activities": [
            "Morning at Ueno Park and Zoo",
            "Visit Tokyo National Museum",
            "Afternoon onsen (hot spring bath)",
            "Farewell dinner in Roppongi"
        ]
    },
    "Day 7": {
        "title": "Departure",
        "activities": [
            "Last-minute souvenir shopping in Shibuya",
            "Visit Shibuya Crossing",
            "Depart from Narita/Haneda Airport"
        ]
    }
}


MOCK_HOTELS = [
    {
        "name": "Hotel Gracery Shinjuku",
        "location": "Shinjuku, Tokyo",
        "price_per_night": 135,
        "rating": 4.3,
        "amenities": ["wifi", "restaurant", "rooftop bar"]
    },
    {
        "name": "The Prince Park Tower Tokyo",
        "location": "Minato, Tokyo",
        "price_per_night": 210,
        "rating": 4.6,
        "amenities": ["wifi", "pool", "spa", "gym", "restaurant"]
    },
    {
        "name": "MUJI Hotel Ginza",
        "location": "Ginza, Tokyo",
        "price_per_night": 178,
        "rating": 4.4,
        "amenities": ["wifi", "restaurant", "minimalist design"]
    },
    {
        "name": "Hoshinoya Tokyo",
        "location": "Otemachi, Tokyo",
        "price_per_night": 450,
        "rating": 4.8,
        "amenities": ["wifi", "onsen", "spa", "fine dining", "ryokan style"]
    },
    {
        "name": "Sakura Hotel Jimbocho",
        "location": "Chiyoda, Tokyo",
        "price_per_night": 65,
        "rating": 3.9,
        "amenities": ["wifi", "cafe", "laundry"]
    },
]


async def search_flights(
    destination: str = "Tokyo",
    max_price: int | None = None,
    delay: float = 1.5
) -> list[dict]:
    """
    Simulate a flight search API call.
    Args:
        destination: Target city (used for logging, mock returns same data)
        max_price: Maximum price filter
        delay: Simulated API latency in seconds
    """
    await asyncio.sleep(delay)

    results = MOCK_FLIGHTS.copy()

    if max_price is not None:
        results = [f for f in results if f["price"] <= max_price]

    return sorted(results, key=lambda f: f["price"])


async def search_hotels(
    city: str = "Tokyo",
    max_price_per_night: int | None = None,
    min_rating: float = 0.0,
    delay: float = 1.0
) -> list[dict]:
    """
    Simulate a hotel search API call.
    Args:
        city: Target city
        max_price_per_night: Maximum nightly rate filter
        min_rating: Minimum star rating filter
        delay: Simulated API latency in seconds
    """
    await asyncio.sleep(delay)

    results = MOCK_HOTELS.copy()

    if max_price_per_night is not None:
        results = [h for h in results if h["price_per_night"] <= max_price_per_night]

    results = [h for h in results if h["rating"] >= min_rating]

    return sorted(results, key=lambda h: h["rating"], reverse=True)
