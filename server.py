def fetch_live_disruptions():
    disruptions = []
    six_hours_ago = datetime.now() - timedelta(hours=6)
    
    # 1. George Municipality Facebook via rss.app - most reliable
    try:
        # Create free RSS at rss.app from https://www.facebook.com/GeorgeMunicipality
        fb_rss = "https://rss.app/feeds/YOUR_RSS_ID.xml"  # replace with yours
        r = requests.get(fb_rss, timeout=5)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text.lower()
            desc = item.description.text.lower()
            pub_date_str = item.pubDate.text
            # Parse date: "Mon, 24 May 2026 08:14:00 +0200"
            pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z").replace(tzinfo=None)
            
            if pub_date > six_hours_ago:
                if any(x in title+desc for x in ['unplanned outage','power outage','electricity','no power','substation trip']):
                    disruptions.append({"type": "Power", "msg": item.title.text, "time": pub_date.strftime("%H:%M"), "area": "See post"})
                elif any(x in title+desc for x in ['burst pipe','water outage','no water','reservoir']):
                    disruptions.append({"type": "Water", "msg": item.title.text, "time": pub_date.strftime("%H:%M"), "area": "See post"})
                elif any(x in title+desc for x in ['road closure','accident','n2','traffic']):
                    disruptions.append({"type": "Traffic", "msg": item.title.text, "time": pub_date.strftime("%H:%M"), "area": "See post"})
    except:
        pass
    
    # 2. Vumatel unplanned incidents
    try:
        r = requests.get("https://www.vumatel.co.za/network-status", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('.outage-item'):
            text = item.get_text(strip=True)
            if 'unplanned' in text.lower() and 'george' in text.lower():
                disruptions.append({"type": "Fibre", "msg": text, "time": "Ongoing", "area": "George"})
    except:
        pass
    
    # 3. Fallback
    if not disruptions:
        disruptions = [{"type": "Status", "msg": "No unplanned disruptions reported in last 6 hours", "time": "", "area": ""}]
    
    return disruptions[:8]

# Update get_cached_data():
@lru_cache(maxsize=1)
def get_cached_data():
    return {
        "time": datetime.now(),
        "dam": fetch_dam_level(),
        "notices": fetch_notices(),
        "disruptions": fetch_live_disruptions(),  # renamed from internet
        "loadshedding": fetch_loadshedding(),
        "weather": fetch_weather_alerts(),
        "crime": fetch_crime_stats(),
        "events": fetch_live_events()
    }
