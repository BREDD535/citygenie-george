from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from functools import lru_cache
import os

app = FastAPI(title="CityGenie George")

CACHE_MINUTES = 15

# VERIFY YEARLY: https://www.george.gov.za/refuse-removal/
REFUSE_SCHEDULE = {
    "Monday": ["Heatherlands", "Denneoord", "Fernridge"],
    "Tuesday": ["Blanco", "Heather Park", "Camphersdrift"],
    "Wednesday": ["George Central", "Dormehlsdrift", "Glen Barrie"],
    "Thursday": ["Thembalethu", "Lawaaikamp", "Borcherds"],
    "Friday": ["Pacaltsdorp", "Delville Park", "Andersonville"],
    "Saturday": ["Leisure Isle", "Wilderness"]
}

# SAFE: Generic contacts. For ward-specific names, check https://www.george.gov.za/council/ward-councillors
COUNCILLORS = {
    "General": {"name": "George Municipality", "phone": "044 801 9111", "area": "Switchboard - ask for your ward councillor"},
    "WhatsApp": {"name": "Municipal WhatsApp", "phone": "044 803 5555", "area": "Report service issues 24/7"},
    "After Hours": {"name": "Emergency Standby", "phone": "044 801 6300", "area": "Water & electricity emergencies only"},
}

def cache_expired(cached_time):
    return datetime.now() - cached_time > timedelta(minutes=CACHE_MINUTES)

@lru_cache(maxsize=1)
def get_cached_data():
    return {
        "time": datetime.now(),
        "dam": fetch_dam_level(),
        "notices": fetch_notices(),
        "disruptions": fetch_live_disruptions(),
        "weather": fetch_weather_alerts(),
        "events": fetch_live_events(),
        "bus_alerts": fetch_bus_alerts(),
        "water_restrictions": fetch_water_restrictions(),
        "refuse": REFUSE_SCHEDULE
    }

def get_data():
    data = get_cached_data()
    if cache_expired(data["time"]):
        get_cached_data.cache_clear()
        data = get_cached_data
