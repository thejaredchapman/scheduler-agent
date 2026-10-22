"""A tiny world for unit tests, small enough to check by hand.

Demo week facts used below: on Monday 26 October 2026 London is UTC+0 and New York UTC-4,
so a 09:00-17:00 day is 09:00-17:00Z in London and 13:00-21:00Z in New York.
"""
from world import World

PEOPLE = [
    {"id": "ana", "name": "Ana Ortiz", "role": "Engineer", "time_zone": "America/New_York",
     "working_hours": ["09:00", "17:00"], "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"]},
    {"id": "ben", "name": "Ben Okafor", "role": "Designer", "time_zone": "Europe/London",
     "working_hours": ["09:00", "17:00"], "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"]},
    {"id": "chen", "name": "Chen Wei", "role": "Analyst", "time_zone": "Asia/Singapore",
     "working_hours": ["09:00", "17:00"], "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"]},
    {"id": "dev", "name": "Dev Patel", "role": "Manager", "time_zone": "America/Denver",
     "working_hours": ["08:00", "16:00"], "working_days": ["Mon", "Tue", "Wed", "Thu"]},
]
ROOMS = [
    {"id": "nook", "name": "Nook", "capacity": 2, "equipment": ["screen"], "time_zone": "America/New_York"},
    {"id": "loft", "name": "Loft", "capacity": 8, "equipment": ["screen", "video"], "time_zone": "America/New_York"},
]
CALENDARS = {
    "ana": [{"start": "2026-10-26T14:00Z", "end": "2026-10-26T15:00Z"}],
    "loft": [{"start": "2026-10-26T13:00Z", "end": "2026-10-26T14:00Z"}],
}


def fixture_world():
    return World(PEOPLE, ROOMS, CALENDARS)
