# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import asyncio
from pathlib import Path
from datetime import datetime
import time

from data_fetcher import fetch_live_scores

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

cricket_data = {
    'last_updated': "Loading...",
    'last_updated_timestamp': time.time(),
    'matches': []
}

def format_match_for_display(match):
    """Format a match into a nice ASCII box with proper line breaks"""
    
    # Get match data
    category = match['category']
    match_info = match['match_info']
    team1 = match['team1']
    team2 = match['team2']
    score1 = match['score1'] if match['score1'] else ""
    score2 = match['score2'] if match['score2'] else ""
    status = match['status']
    is_live = "●" if match['is_live'] else "○"
    
    # Create a fixed width box
    box_width = 37  # Width of content inside the box
    
    box = []
    box.append("+---------------------------------------+")
    box.append(f"| {category[:box_width].ljust(box_width)} |")
    box.append("|                                       |")
    
    # Handle match info - split into multiple lines if needed
    match_info_words = f"{is_live} {match_info}".split()
    match_info_lines = []
    current_line = ""
    
    for word in match_info_words:
        if len(current_line + " " + word) <= box_width:
            current_line += " " + word if current_line else word
        else:
            match_info_lines.append(current_line)
            current_line = word
    
    if current_line:
        match_info_lines.append(current_line)
    
    for line in match_info_lines:
        box.append(f"| {line.ljust(box_width)} |")
    
    box.append("|                                       |")
    
    # Format team names and scores
    team1_score = f"{team1[:20].ljust(20)} {score1}"
    team2_score = f"{team2[:20].ljust(20)} {score2}"
    
    box.append(f"| {team1_score[:box_width].ljust(box_width)} |")
    box.append(f"| {team2_score[:box_width].ljust(box_width)} |")
    box.append("|                                       |")
    
    # Handle status - split into multiple lines if needed
    status_words = status.split()
    status_lines = []
    current_line = ""
    
    for word in status_words:
        if len(current_line + " " + word) <= box_width:
            current_line += " " + word if current_line else word
        else:
            status_lines.append(current_line)
            current_line = word
    
    if current_line:
        status_lines.append(current_line)
    
    for line in status_lines:
        box.append(f"| {line.ljust(box_width)} |")
    
    box.append("+---------------------------------------+")
    
    return "\n".join(box)

# Add custom Jinja2 filters
@app.on_event("startup")
async def add_jinja_filters():
    """Add custom filters to Jinja2 templates"""
    templates.env.filters["ljust"] = lambda s, width: str(s).ljust(width)
    templates.env.filters["rjust"] = lambda s, width: str(s).rjust(width)
    templates.env.filters["truncate"] = lambda s, length: str(s)[:length] if s else ""
    templates.env.filters["default"] = lambda s, default_value: s if s else default_value

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main page with cricket scores"""
    # Calculate how long since the last update
    seconds_ago = int(time.time() - cricket_data['last_updated_timestamp'])
    
    if seconds_ago < 60:
        time_ago = f"{seconds_ago} seconds ago"
    else:
        minutes_ago = seconds_ago // 60
        if minutes_ago == 1:
            time_ago = "1 minute ago"
        else:
            time_ago = f"{minutes_ago} minutes ago"
    
    # Format matches into ASCII boxes
    formatted_matches = []
    for match in cricket_data['matches']:
        formatted_matches.append(format_match_for_display(match))
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "match_rows": formatted_matches,
        "last_updated": cricket_data['last_updated'],
        "time_ago": time_ago
    })

async def update_cricket_data():
    """Background task to update cricket data every 2 minutes"""
    global cricket_data
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # Fetch the latest data
            print(f"[{current_time}] Fetching cricket data...")
            fresh_data = fetch_live_scores()
            if fresh_data and fresh_data.get('matches'):
                cricket_data = fresh_data
                # Add timestamp for "time ago" calculation
                cricket_data['last_updated_timestamp'] = time.time()
                print(f"[{current_time}] Data updated, found {len(fresh_data['matches'])} matches")
            else:
                print(f"[{current_time}] No data received or empty matches list")
        except Exception as e:
            print(f"[{current_time}] Error updating cricket data: {e}")
        
        # Wait for 2 minutes before updating again
        await asyncio.sleep(120)

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    # Initial data fetch
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    global cricket_data
    try:
        print(f"[{current_time}] Initial data fetch...")
        initial_data = fetch_live_scores()
        if initial_data:
            cricket_data = initial_data
            # Add timestamp for "time ago" calculation
            cricket_data['last_updated_timestamp'] = time.time()
            print(f"[{current_time}] Initial data loaded, found {len(initial_data['matches'])} matches")
    except Exception as e:
        print(f"[{current_time}] Error fetching initial cricket data: {e}")
    
    # Start background task
    asyncio.create_task(update_cricket_data())

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)