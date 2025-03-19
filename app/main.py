# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import asyncio
from pathlib import Path
from datetime import datetime
import time
import json
import os
from itertools import groupby

from data_fetcher import fetch_live_scores, DATA_FILE, DATA_FOLDER

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Default data structure
default_cricket_data = {
    'last_updated': "Loading...",
    'last_updated_timestamp': time.time(),
    'matches': [],
    'tournaments': []
}

def load_cricket_data():
    """Load cricket data from the JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return default_cricket_data

def format_match_for_display(match, use_symbols=True):
    """Format a match into a nice ASCII box with proper line breaks"""
    
    # Get match data
    match_info = match['match_info'].replace("\n", " ").strip()
    team1 = match['team1']
    team2 = match['team2']
    score1 = match['score1'] if match['score1'] else ""
    score2 = match['score2'] if match['score2'] else ""
    status = match['status']
    
    # Fixed box dimensions
    box_width = 37  # Width of content inside the box
    
    # Create the box content
    box = []
    box.append("+---------------------------------------+")
    
    # Prepare the match info with live indicator
    if use_symbols:
        indicator = "● " if match['is_live'] else "○ "
    else:
        indicator = "LIVE " if match['is_live'] else ""
    
    # Combine indicator with match info
    full_info = indicator + match_info
    
    # Break info into lines that fit the box width
    words = full_info.split()
    lines = []
    current_line = ""
    
    for word in words:
        # If adding this word would exceed box width, start a new line
        if len(current_line) + len(word) + 1 > box_width:
            lines.append(current_line)
            current_line = word
        else:
            # Add word to current line (with space if not first word)
            if current_line:
                current_line += " " + word
            else:
                current_line = word
    
    # Add the last line if there's anything left
    if current_line:
        lines.append(current_line)
    
    # Add each info line to the box
    for line in lines:
        box.append(f"| {line.ljust(box_width)} |")
    
    # Add a blank line before teams
    box.append("|                                       |")
    
    # Add teams and scores
    team1_line = f"{team1[:20].ljust(20)} {score1}"
    team2_line = f"{team2[:20].ljust(20)} {score2}"
    
    box.append(f"| {team1_line[:box_width].ljust(box_width)} |")
    box.append(f"| {team2_line[:box_width].ljust(box_width)} |")
    
    # Add a blank line before status
    box.append("|                                       |")
    
    # Add status with wrapping
    words = status.split()
    current_line = ""
    
    for word in words:
        if len(current_line) + len(word) + 1 > box_width:
            box.append(f"| {current_line.ljust(box_width)} |")
            current_line = word
        else:
            if current_line:
                current_line += " " + word
            else:
                current_line = word
    
    if current_line:
        box.append(f"| {current_line.ljust(box_width)} |")
    
    # Close the box
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
    # Load the latest cricket data
    cricket_data = load_cricket_data()
    
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
    
    # Use the pre-sorted tournament order from the JSON
    tournament_list = []
    
    # Group matches by tournament in the order defined in tournaments list
    for tournament_name in cricket_data.get('tournaments', []):
        matches = [m for m in cricket_data['matches'] if m['category'] == tournament_name]
        formatted_matches = [format_match_for_display(match) for match in matches]
        
        tournament_list.append({
            'name': tournament_name,
            'matches': formatted_matches
        })
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "tournaments": tournament_list,
        "last_updated": cricket_data['last_updated'],
        "time_ago": time_ago
    })

@app.get("/plain.txt", response_class=PlainTextResponse)
async def plain_text():
    """Serve the cricket scores as plain text"""
    # Load the latest cricket data
    cricket_data = load_cricket_data()
    
    # Build the plain text output
    output = []
    output.append("CRICLITE.COM")
    output.append("Live cricket scores in plain text")
    output.append("=================================================================")
    
    # Use the pre-sorted tournament order from the JSON
    for tournament_name in cricket_data.get('tournaments', []):
        matches = [m for m in cricket_data['matches'] if m['category'] == tournament_name]
        
        # Add a blank line between tournaments
        output.append("")
        output.append(tournament_name)
        
        # Add each match in this tournament
        for match in matches:
            # Use format_match_for_display but change the live indicator to be text-based
            formatted_match = format_match_for_display(match, use_symbols=False)
            output.append(formatted_match)
    
    output.append("=================================================================")
    output.append(f"Last updated: {cricket_data['last_updated']}")
    output.append("Refresh page to update scores.")
    
    # Join all lines and return
    return "\n".join(output)

async def update_cricket_data():
    """Background task to update cricket data every 2 minutes"""
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # Fetch the latest data (data_fetcher now handles saving to file)
            print(f"[{current_time}] Fetching cricket data...")
            fetch_live_scores()
            print(f"[{current_time}] Data updated")
        except Exception as e:
            print(f"[{current_time}] Error updating cricket data: {e}")
        
        # Wait for 2 minutes before updating again
        await asyncio.sleep(120)

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    # Initial data fetch
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        print(f"[{current_time}] Initial data fetch...")
        fetch_live_scores()  # This now saves to JSON file directly
        print(f"[{current_time}] Initial data loaded")
    except Exception as e:
        print(f"[{current_time}] Error fetching initial cricket data: {e}")
    
    # Start background task
    asyncio.create_task(update_cricket_data())

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)