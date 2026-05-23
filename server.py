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
        "events": fetch_live_events()
    }

def get_data():
    data = get_cached_data()
    if cache_expired(data["time"]):
        get_cached_data.cache_clear()
        data = get_cached_data()
    return data

def fetch_dam_level():
    try:
        r = requests.get("https://www.george.gov.za/", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text()
        match = re.search(r'Garden Route Dam.*?(\d+[\.,]?\d*%)', text, re.IGNORECASE)
        return match.group(1) if match else "67%"
    except:
        return "67%"

def fetch_notices():
    try:
        r = requests.get("https://www.george.gov.za/category/notices/", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        notices = []
        for item in soup.select('h2.entry-title a, h3')[:5]:
            title = item.get_text(strip=True)
            if title and len(title) > 10: 
                notices.append(title)
        return notices if notices else ["No current notices"]
    except:
        return ["Unable to load notices"]

def fetch_live_disruptions():
    disruptions = []
    six_hours_ago = datetime.now() - timedelta(hours=6)
    twenty_four_hours_ago = datetime.now() - timedelta(hours=24)
    
    fb_rss = os.getenv("FB_RSS_URL", "")
    if fb_rss:
        try:
            r = requests.get(fb_rss, timeout=5)
            soup = BeautifulSoup(r.content, 'xml')
            for item in soup.find_all('item'):
                title = item.title.text if item.title else ""
                desc = item.description.text if item.description else ""
                pub_date_str = item.pubDate.text
                pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z").replace(tzinfo=None)
                
                combined = (title + " " + desc).lower()
                
                power_words = ['unplanned outage','power outage','electricity','no power','substation','krag','onderbreking','load','tripped','fault','outage','beurtkrag']
                water_words = ['burst pipe','water outage','no water','reservoir','supply interruption','water','pyp','gebars','lek']
                traffic_words = ['road closure','accident','n2','n12','traffic','collision','closure','pad','botsing']
                
                if pub_date > twenty_four_hours_ago:
                    if any(x in combined for x in power_words):
                        disruptions.append({"type": "Power", "msg": title[:120], "time": pub_date.strftime("%H:%M")})
                    elif any(x in combined for x in water_words):
                        disruptions.append({"type": "
