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

def format_team_and_score(team_name, score, max_width=35):
    """Format team name and score to fit within max_width"""
    # If team name is too long and we have a score, abbreviate the team name
    if len(team_name) > 20 and score:
        parts = team_name.split()
        if len(parts) > 1:
            # Use initials for middle parts
            abbreviated = parts[0] + ' ' + ' '.join(p[0] + '.' for p in parts[1:-1]) + ' ' + parts[-1]
            team_name = abbreviated
    
    team_display = team_name[:20].ljust(20)
    score_display = format_score(score, 15)
    return f"{team_display} {score_display}"

def format_score(score, max_width=15):
    """Format score to fit within max_width"""
    if not score:
        return ""
    
    # If score too long, try more compact format
    if len(score) > max_width:
        # Remove unnecessary spaces, shorten common terms
        score = score.replace(" ov)", ")")
        score = score.replace("    ", " ")
    
    return score[:max_width]

def format_multiline_field(text, box_width):
    """Format text into multiple lines that fit within box_width"""
    words = text.split()
    lines = []
    current = ""
    
    for word in words:
        if len(current + " " + word if current else word) <= box_width:
            current = current + " " + word if current else word
        else:
            lines.append(current)
            current = word
    
    if current:
        lines.append(current)
    
    return [line.ljust(box_width) for line in lines]


def format_match_for_display(match, use_symbols=True):
    """Format a match into a nice ASCII box with consistent dimensions"""
    
    # Get match data
    match_info = match['match_info']
    team1 = match['team1']
    team2 = match['team2']
    score1 = match['score1'] if match['score1'] else ""
    score2 = match['score2'] if match['score2'] else ""
    status = match['status']
    is_live = match['is_live']
    category = match['category']
    
    # Fixed dimensions - these should never change
    OUTER_WIDTH = 41  # Total width including borders
    INNER_WIDTH = 37  # Content width
    STANDARD_HEIGHT = 12  # Standard number of lines for each box
    
    # Create a standard box template
    top_border = "+" + "-" * (OUTER_WIDTH - 2) + "+"
    bottom_border = top_border
    empty_line = "| " + " " * INNER_WIDTH + " |"
    
    # Build the box content
    box_lines = []
    box_lines.append(top_border)
    
    # Format match info - always prefix with [LIVE] if live
    info_prefix = "[LIVE] " if is_live else ""
    match_info_cleaned = match_info.replace("\n", " ").strip()
    
    # Split match info into lines that fit
    info_lines = []
    current_line = info_prefix
    
    for word in match_info_cleaned.split():
        if len(current_line + word) + 1 <= INNER_WIDTH:
            current_line += (word + " ")
        else:
            info_lines.append(current_line.strip())
            current_line = word + " "
    
    if current_line.strip():
        info_lines.append(current_line.strip())
    
    # Add match info lines to box
    for line in info_lines:
        padded_line = line.ljust(INNER_WIDTH)
        box_lines.append(f"| {padded_line} |")
    
    # Add empty line
    box_lines.append(empty_line)
    
    # Add tournament category
    if category:
        category_line = category[:INNER_WIDTH].ljust(INNER_WIDTH)
        box_lines.append(f"| {category_line} |")
        box_lines.append(empty_line)
    
    # Team 1 with score
    team1_name = team1[:20].ljust(20)  # Fixed width for team name
    score1_display = score1[:16] if score1 else ""  # Limit score width
    team1_line = f"{team1_name} {score1_display}"
    team1_line = team1_line[:INNER_WIDTH].ljust(INNER_WIDTH)
    box_lines.append(f"| {team1_line} |")
    
    # Team 2 with score
    team2_name = team2[:20].ljust(20)  # Fixed width for team name
    score2_display = score2[:16] if score2 else ""  # Limit score width
    team2_line = f"{team2_name} {score2_display}"
    team2_line = team2_line[:INNER_WIDTH].ljust(INNER_WIDTH)
    box_lines.append(f"| {team2_line} |")
    
    # Add empty line
    box_lines.append(empty_line)
    
    # Status lines
    status_lines = []
    current_line = ""
    
    for word in status.split():
        if len(current_line + word) + 1 <= INNER_WIDTH:
            current_line += (word + " ")
        else:
            status_lines.append(current_line.strip())
            current_line = word + " "
    
    if current_line.strip():
        status_lines.append(current_line.strip())
    
    # Add status lines
    for line in status_lines:
        padded_line = line.ljust(INNER_WIDTH)
        box_lines.append(f"| {padded_line} |")
    
    # Add bottom border
    box_lines.append(bottom_border)
    
    # Normalize box height by adding or removing empty lines
    current_height = len(box_lines)
    
    if current_height < STANDARD_HEIGHT:
        # Box is too short, add empty lines before the bottom border
        bottom_border = box_lines.pop()  # Remove bottom border
        while len(box_lines) < STANDARD_HEIGHT - 1:
            box_lines.append(empty_line)
        box_lines.append(bottom_border)  # Add bottom border back
    elif current_height > STANDARD_HEIGHT:
        # Box is too tall, preserve important elements and trim the middle
        # Keep: top border, first 2 lines (match info), category, teams, last 2 lines (result)
        top_section = box_lines[:4]  # Top border + match info + empty line
        middle_section = box_lines[4:-3]  # Category, teams, etc.
        bottom_section = box_lines[-3:]  # Status and bottom border
        
        # Calculate how many middle lines we can keep
        middle_lines_to_keep = STANDARD_HEIGHT - len(top_section) - len(bottom_section)
        
        # Rebuild the box
        box_lines = top_section + middle_section[:middle_lines_to_keep] + bottom_section
    
    # Convert to a string with line breaks
    box_text = "\n".join(box_lines)
    
    return box_text


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
    """Serve the main page with cricket scores, grouped by status"""
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
    
    # Add cache control headers based on data freshness
    cache_time = 60 if seconds_ago < 120 else 30
    
    # Group matches by status
    live_matches = []
    completed_matches = []
    upcoming_matches = []
    
    for match in cricket_data['matches']:
        # Enhanced status determination
        match_status = match['match_status'] 
        
        formatted_match = format_match_for_display(match)
        
        if match_status == "live":
            live_matches.append(formatted_match)
        elif match_status == "completed":
            completed_matches.append(formatted_match)
        else:  # scheduled or unknown
            upcoming_matches.append(formatted_match)
    
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "live_matches": live_matches,
        "completed_matches": completed_matches,
        "upcoming_matches": upcoming_matches,
        "last_updated": cricket_data['last_updated'],
        "time_ago": time_ago
    })
    
    response.headers.update({"Cache-Control": f"max-age={cache_time}"})
    return response

@app.get("/plain.txt", response_class=PlainTextResponse)
async def plain_text():
    """Serve the cricket scores as plain text, grouped by status"""
    # Load the latest cricket data
    cricket_data = load_cricket_data()
    
    # Group matches by status
    live_matches = []
    completed_matches = []
    upcoming_matches = []
    
    for match in cricket_data['matches']:
        # Enhanced status determination
        match_status = match['match_status']
        
        formatted_match = format_match_for_display(match, use_symbols=False)
        
        if match_status == "live":
            live_matches.append(formatted_match)
        elif match_status == "completed":
            completed_matches.append(formatted_match)
        else:  # scheduled or unknown
            upcoming_matches.append(formatted_match)
    
    # Build the plain text output
    output = []
    output.append("CRICLITE.COM")
    output.append("Live cricket scores in plain text")
    output.append("=================================================================")
    
    # Add live matches
    if live_matches:
        output.append("")
        output.append("LIVE")
        output.append("")
        for match in live_matches:
            output.append(match)
            output.append("")  # Add space between matches
    
    # Add upcoming matches
    if upcoming_matches:
        output.append("")
        output.append("UPCOMING")
        output.append("")
        for match in upcoming_matches:
            output.append(match)
            output.append("")  # Add space between matches
    
    # Add completed matches
    if completed_matches:
        output.append("")
        output.append("COMPLETED")
        output.append("")
        for match in completed_matches:
            output.append(match)
            output.append("")  # Add space between matches
    
    output.append("=================================================================")
    output.append(f"Last updated: {cricket_data['last_updated']}")
    output.append("Refresh page to update scores.")
    
    # Join all lines and return
    return "\n".join(output)

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    """About page with information about the site"""
    return templates.TemplateResponse("about.html", {
        "request": request
    })

async def update_cricket_data():
    """Background task to update cricket data every 2 minutes"""
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # Fetch the latest data (data_fetcher now handles saving to file)
            print(f"[{current_time}] Fetching cricket data...")
            cricket_data = fetch_live_scores()
            
            # Adaptive refresh timing based on live matches
            live_matches = sum(1 for match in cricket_data['matches'] if match['is_live'])
            wait_time = 90 if live_matches > 0 else 180  # 1.5 mins or 3 mins
            
            print(f"[{current_time}] Data updated. Found {live_matches} live matches. Next update in {wait_time} seconds.")
        except Exception as e:
            print(f"[{current_time}] Error updating cricket data: {e}")
            wait_time = 120  # Default to 2 minutes on error
        
        # Wait before updating again
        await asyncio.sleep(wait_time)

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