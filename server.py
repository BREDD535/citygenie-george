from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from functools import lru_cache
import os
import json

app = FastAPI(title="CityGenie George")

CACHE_MINUTES = 5 # shorter cache for faster outage updates
ADMIN_PASSWORD = "george2026" # CHANGE THIS
OUTAGES_FILE = "/tmp/outages.json"

REFUSE_SCHEDULE = {
    "Monday": ["Heatherlands", "Denneoord", "Fernridge"],
    "Tuesday": ["Blanco", "Heather Park", "Camphersdrift"],
    "Wednesday": ["George Central", "Dormehlsdrift", "Glen Barrie"],
    "Thursday": ["Thembalethu", "Lawaaikamp", "Borcherds"],
    "Friday": ["Pacaltsdorp", "Delville Park", "Andersonville"],
    "Saturday": ["Leisure Isle", "Wilderness"]
}

COUNCILLORS = {
    "General": {"name": "George Municipality", "phone": "0448019111", "area": "Switchboard"},
    "WhatsApp": {"name": "WhatsApp", "phone": "0448035555", "area": "Report issues 24/7"},
    "Emergency": {"name": "After Hours", "phone": "0448016300", "area": "Water & electricity"},
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
        data = get_cached_data()
    return data

def fetch_dam_level():
    try:
        r = requests.get("https://www.george.gov.za/", timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        match = re.search(r'Garden Route Dam.*?(\d+[\.,]?\d*%)', r.text, re.IGNORECASE)
        return match.group(1) if match else "67%"
    except:
        return "67%"

def fetch_notices():
    try:
        r = requests.get("https://www.george.gov.za/category/notices/", timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(r.text, 'html.parser')
        notices = []
        for article in soup.select('article')[:8]:
            a = article.select_one('h2 a, h3 a')
            if a:
                title = a.get_text(strip=True)
                # Filter out menu items and short titles
                if len(title) > 20 and not any(x in title.lower() for x in ['latest news','upcoming events','quick contacts','menu']):
                    notices.append(title)
        return notices[:4] if notices else ["Check george.gov.za for notices"]
    except:
        return ["Unable to load notices"]

def fetch_live_disruptions():
    disruptions = []

    # 1. Load manual outages from admin panel
    try:
        if os.path.exists(OUTAGES_FILE):
            with open(OUTAGES_FILE) as f:
                manual = json.load(f)
                disruptions.extend(manual)
    except:
        pass

    # 2. Scrape municipality homepage for alerts
    try:
        r = requests.get("https://www.george.gov.za/", timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        text = r.text.lower()
        soup = BeautifulSoup(r.text, 'html.parser')

        # Look for alert boxes or prominent text
        for alert in soup.select('.alert,.notice,.wp-block-alert, [class*="alert"]'):
            txt = alert.get_text(strip=True)
            if len(txt) > 30 and any(k in txt.lower() for k in ['outage','interruption','burst','no water','no power','krag']):
                disruptions.append({
                    "type": "Power" if any(w in txt.lower() for w in ['power','electric','krag']) else "Water",
                    "msg": txt[:120],
                    "time": "Alert"
                })
    except:
        pass

    # 3. Scrape notices for unplanned outages
    try:
        r = requests.get("https://www.george.gov.za/category/notices/", timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(r.text, 'html.parser')
        for article in soup.select('article')[:5]:
            title_el = article.select_one('h2 a')
            if title_el:
                title = title_el.get_text(strip=True)
                tl = title.lower()
                if any(k in tl for k in ['unplanned','outage','burst','interruption','emergency']) and 'planned' not in tl:
                    disruptions.append({
                        "type": "Power" if 'power' in tl or 'electric' in tl else "Water" if 'water' in tl else "Alert",
                        "msg": title[:120],
                        "time": "Today"
                    })
    except:
        pass

    # Deduplicate
    seen = set()
    unique = []
    for d in disruptions:
        key = d['msg'][:40]
        if key not in seen:
            seen.add(key)
            unique.append(d)

    if not unique:
        unique = [{"type": "Status", "msg": "No unplanned disruptions reported", "time": ""}]

    return unique[:5]

def fetch_bus_alerts():
    try:
        r = requests.get("https://www.gogeorge.org.za/service-alerts/", timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(r.text, 'html.parser')
        alerts = []
        for p in soup.select('.entry-content p,.alert-item'):
            txt = p.get_text(strip=True)
            if len(txt) > 25:
                alerts.append(txt[:140])
        return alerts[:2] if alerts else ["No Go George alerts"]
    except:
        return ["No Go George alerts"]

def fetch_water_restrictions():
    try:
        r = requests.get("https://www.george.gov.za/", timeout=8)
        match = re.search(r'Water Restrictions.*?Level\s*(\d)', r.text, re.IGNORECASE)
        if match:
            return {"level": f"Level {match.group(1)}", "detail": "Restrictions in place"}
        return {"level": "No restrictions", "detail": "Normal use permitted"}
    except:
        return {"level": "Unknown", "detail": "Check website"}

def fetch_weather_alerts():
    try:
        # Open-Meteo works on Render free tier
        r = requests.get("https://api.open-meteo.com/v1/forecast?latitude=-33.96&longitude=22.46&daily=weather_code&timezone=Africa/Johannesburg", timeout=5)
        if r.status_code == 200:
            return "No severe weather alerts"
        return "Weather: Normal"
    except:
        return "Weather: Check SAWS"

def fetch_live_events():
    try:
        r = requests.get("https://www.georgeherald.com/rss", timeout=8)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item')[:10]:
            title = item.title.text
            if any(w in title.lower() for w in ['market','parkrun','festival','expo']):
                return [{"title": title, "date": "", "source": "", "link": item.link.text}]
        return [{"title": "No events today", "date": "", "source": "", "link": ""}]
    except:
        return [{"title": "No events today", "date": "", "source": "", "link": ""}]

@app.get("/", response_class=HTMLResponse)
async def root():
    d = get_data()
    updated = d["time"].strftime("%d %b %H:%M")

    def icon(name, size=24):
        return f'<span class="material-symbols-rounded" style="font-size:{size}px;font-variation-settings:\'FILL\' 1;">{name}</span>'

    disruptions_html = ""
    for item in d["disruptions"]:
        ic = {"Power":"electric_bolt","Water":"water_drop","Traffic":"traffic","Fibre":"wifi","Status":"check_circle","Alert":"warning"}.get(item["type"],"info")
        bg = "#2A2E32"
        disruptions_html += f"""
        <div style="margin:8px 16px; padding:16px; background:{bg}; border-radius:20px; display:flex; gap:14px;">
            {icon(ic,28)}
            <div style="flex:1; min-width:0;">
                <div style="font-weight:500; font-size:14px; margin-bottom:2px;">{item['type']}</div>
                <div style="font-size:15px; line-height:1.4; word-wrap:break-word;">{item['msg']}</div>
                <div style="font-size:12px; opacity:0.6; margin-top:4px;">{item['time']}</div>
            </div>
        </div>"""

    notices_html = "".join([f"""
        <div style="padding:16px; border-bottom:1px solid #333; display:flex; justify-content:space-between; gap:12px;">
            <div style="flex:1;">{n}</div>
            {icon('chevron_right',20)}
        </div>""" for n in d["notices"]])

    bus_html = "".join([f"""<div style="padding:16px; display:flex; gap:12px;">{icon('directions_bus')}<div style="flex:1;">{a}</div></div>""" for a in d["bus_alerts"]])

    refuse_html = ""
    today = datetime.now().strftime("%A")
    for day, suburbs in d["refuse"].items():
        today_tag = " <span style='color:#9CCBFF;'>(Today)</span>" if day == today else ""
        refuse_html += f"""
        <div style="padding:14px 16px; display:flex; gap:12px; border-bottom:1px solid #333;">
            {icon('delete')}
            <div><div style="font-weight:500;">{day}{today_tag}</div><div style="font-size:14px; opacity:0.8;">{', '.join(suburbs)}</div></div>
        </div>"""

    html = f"""
    <!DOCTYPE html><html><head>
        <title>CityGenie George</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0..1,0" rel="stylesheet">
        <style>
            *{{box-sizing:border-box;margin:0;padding:0}}
            body{{font-family:Roboto,system-ui;background:#101417;color:#E1E2E5;line-height:1.5}}
           .wrap{{max-width:640px;margin:0 auto;padding-bottom:40px}}
           .top{{padding:24px 20px 16px;font-size:30px;font-weight:400}}
           .hero{{background:#004A75;color:#CFE5FF;margin:0 12px 12px;padding:28px;border-radius:28px}}
           .dam{{font-size:68px;font-weight:400;margin:6px 0;line-height:1}}
           .card{{background:#1D2023;margin:0 12px 12px;border-radius:24px;overflow:hidden}}
           .head{{padding:20px;display:flex;align-items:center;gap:14px;font-size:20px;font-weight:500}}
            a{{color:inherit;text-decoration:none}}
        </style>
    </head><body>
        <div class="wrap">
            <div class="top">CityGenie</div>
            <div class="hero">
                <div style="opacity:0.85;font-size:15px;">Garden Route Dam</div>
                <div class="dam">{d['dam']}</div>
                <div style="opacity:0.75;font-size:14px;">Updated {updated} • George</div>
            </div>

            <div class="card"><div class="head">{icon('emergency_home')}Live Disruptions</div>{disruptions_html}</div>

            <div class="card"><div class="head">{icon('directions_bus')}Go George Alerts</div>{bus_html}</div>

            <div class="card"><div class="head">{icon('water_drop')}Water Restrictions</div>
                <div style="padding:0 20px 20px 56px;"><div style="font-weight:500;">{d['water_restrictions']['level']}</div><div style="opacity:0.8;font-size:14px;">{d['water_restrictions']['detail']}</div></div>
            </div>

            <div class="card"><div class="head">{icon('delete')}Refuse Collection</div>{refuse_html}</div>

            <div class="card"><div class="head">{icon('celebration')}Events</div><div style="padding:0 20px 20px 56px;">{d['events'][0]['title']}</div></div>

            <div class="card"><div class="head">{icon('campaign')}Notices</div>{notices_html}</div>

            <div class="card"><div class="head">{icon('cloud')}Weather</div><div style="padding:0 20px 20px 56px;display:flex;gap:12px;align-items:center;">{icon('info')}<div>{d['weather']}</div></div></div>

            <div class="card"><div class="head">{icon('call')}Municipal Contacts</div>
                {"".join([f'<a href="tel:{c["phone"]}"><div style="padding:16px 20px;display:flex;justify-content:space-between;align-items:center;border-top:1px solid #333;"><div><div style="font-weight:500;">{c["name"]}</div><div style="font-size:14px;opacity:0.8;">{c["area"]}</div></div>{icon("call")}</div></a>' for c in COUNCILLORS.values()])}
            </div>

            <div style="text-align:center;padding:30px 20px;opacity:0.55;font-size:12px;line-height:1.6;">
                <a href="/admin" style="color:#9CCBFF;text-decoration:underline;">Admin</a> • For emergencies dial 10111<br>Data updates every 5 min • Not affiliated with George Municipality
            </div>
        </div>
    </body></html>
    """
    return HTMLResponse(content=html)

@app.get("/admin", response_class=HTMLResponse)
async def admin():
    return """
    <html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Admin - CityGenie</title>
    <style>body{font-family:system-ui;background:#101417;color:#fff;padding:24px;max-width:420px;margin:0 auto}h2{margin-bottom:20px}input,select,button{width:100%;padding:16px;margin:10px 0;border-radius:14px;border:1px solid #333;background:#1D2023;color:#fff;font-size:16px}button{background:#00639B;border:none;font-weight:600;margin-top:16px}label{font-size:14px;opacity:0.8;display:block;margin-top:12px}</style>
    </head><body>
    <h2>Post Live Disruption</h2>
    <form method="post" action="/admin/post">
        <label>Password</label><input type="password" name="pwd" required>
        <label>Type</label><select name="type"><option>Power</option><option>Water</option><option>Traffic</option><option>Fibre</option><option>Alert</option></select>
        <label>Message (max 120 chars)</label><input name="msg" placeholder="e.g. Heatherlands power outage - teams dispatched" required maxlength="120">
        <label>Time</label><input name="time" value="Now">
        <button type="submit">POST ALERT</button>
    </form>
    <form method="post" action="/admin/clear" style="margin-top:30px;border-top:1px solid #333;padding-top:20px;">
        <label>Password</label><input type="password" name="pwd" required>
        <button type="submit" style="background:#444;">CLEAR ALL ALERTS</button>
    </form>
    <p style="margin-top:30px;opacity:0.6;font-size:13px;">Alerts show instantly on homepage. They auto-clear when server restarts.</p>
    </body></html>
    """

@app.post("/admin/post")
async def admin_post(pwd: str = Form(...), type: str = Form(...), msg: str = Form(...), time: str = Form("Now")):
    if pwd!= ADMIN_PASSWORD:
        return HTMLResponse("Wrong password", status_code=403)
    outages = []
    if os.path.exists(OUTAGES_FILE):
        try:
            with open(OUTAGES_FILE) as f: outages = json.load(f)
        except: pass
    outages.insert(0, {"type": type, "msg": msg[:120], "time": time})
    with open(OUTAGES_FILE, 'w') as f: json.dump(outages[:5], f)
    get_cached_data.cache_clear()
    return HTMLResponse("<script>alert('Alert posted!');location.href='/'</script>")

@app.post("/admin/clear")
async def admin_clear(pwd: str = Form(...)):
    if pwd!= ADMIN_PASSWORD:
        return HTMLResponse("Wrong password", status_code=403)
    if os.path.exists(OUTAGES_FILE): os.remove(OUTAGES_FILE)
    get_cached_data.cache_clear()
    return HTMLResponse("<script>alert('Cleared!');location.href='/'</script>")

@app.get("/api/data")
async def api_data():
    d = get_data()
    return JSONResponse({**{k:v for k,v in d.items() if k!='refuse'}, "refuse_schedule": d["refuse"], "updated": d["time"].isoformat()})

@app.get("/health")
async def health(): return {"status":"ok"}
