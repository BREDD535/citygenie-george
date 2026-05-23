from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, StreamingResponse
import asyncio
import json
import random
from datetime import datetime

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("static/manifest.json")

@app.get("/")
async def home(request: Request):
    data = {
        "dam_level": 68.5,
        "outages": ["Ward 12: 14:00-16:00", "Ward 3: 09:00-11:00"],
        "events": ["Water maintenance: 22 May", "Loadshedding Stage 2"]
    }
    return templates.TemplateResponse("index.html", {"request": request, "data": data})

@app.get("/stream")
async def event_stream():
    async def generate():
        while True:
            payload = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "dam_level": round(68 + random.uniform(-1, 1), 1)
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(5)
    return StreamingResponse(generate(), media_type="text/event-stream")
