# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import asyncio
from pathlib import Path
from datetime import datetime
import time
import json
import os

from app.data_fetcher import fetch_live_scores, DATA_FILE, DATA_FOLDER

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

# Store previous data and current interval for adaptive updates
last_cricket_data = None
current_update_interval = 120  # Start with 2 minutes
next_update_time = None

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
    STANDARD_HEIGHT = 13  # Standard number of lines for each box
    
    # Create a standard box template
    top_border = "+" + "-" * (OUTER_WIDTH - 2) + "+"
    bottom_border = top_border
    empty_line = "| " + " " * INNER_WIDTH + " |"
    score_separator = "|" + "-" * (OUTER_WIDTH - 2) + "|"
    
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
        # Handle long category names by wrapping if needed
        if len(category) > INNER_WIDTH:
            # Split long category name into multiple lines
            cat_words = category.split()
            cat_line = ""
            for word in cat_words:
                if len(cat_line + word) + 1 <= INNER_WIDTH:
                    cat_line += (word + " ")
                else:
                    box_lines.append(f"| {cat_line.strip().ljust(INNER_WIDTH)} |")
                    cat_line = word + " "
            
            if cat_line.strip():
                box_lines.append(f"| {cat_line.strip().ljust(INNER_WIDTH)} |")
        else:
            category_line = category[:INNER_WIDTH].ljust(INNER_WIDTH)
            box_lines.append(f"| {category_line} |")
        
        box_lines.append(empty_line)
    
    # Add separator before scores
    box_lines.append(score_separator)
    
    # Process team scores
    # Team 1 and score
    if len(team1) + len(score1) + 1 <= INNER_WIDTH:
        # Can fit on one line
        box_lines.append(f"| {(team1 + ' ' + score1).ljust(INNER_WIDTH)} |")
    else:
        # Need to split across lines
        box_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
        box_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
    
    # Team 2 and score
    if len(team2) + len(score2) + 1 <= INNER_WIDTH:
        # Can fit on one line
        box_lines.append(f"| {(team2 + ' ' + score2).ljust(INNER_WIDTH)} |")
    else:
        # Need to split across lines
        box_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
        box_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
    
    # Add separator after scores
    box_lines.append(score_separator)
    
    # Process status text with wrapping
    status_words = status.split()
    status_line = ""
    status_lines = []
    
    for word in status_words:
        if len(status_line + word) + 1 <= INNER_WIDTH:
            status_line += (word + " ")
        else:
            status_lines.append(status_line.strip())
            status_line = word + " "
    
    if status_line.strip():
        status_lines.append(status_line.strip())
    
    # Add status lines
    for line in status_lines:
        box_lines.append(f"| {line.ljust(INNER_WIDTH)} |")
    
    # Add bottom border
    box_lines.append(bottom_border)
    
    # Ensure exact height matching
    if len(box_lines) < STANDARD_HEIGHT:
        # Box is too short, add empty lines before bottom border
        bottom_border = box_lines.pop()  # Remove bottom border
        
        # Add empty lines until we reach the standard height - 1
        while len(box_lines) < STANDARD_HEIGHT - 1:
            box_lines.append(empty_line)
            
        # Add back bottom border
        box_lines.append(bottom_border)
    elif len(box_lines) > STANDARD_HEIGHT:
        # Box is too tall, need to trim intelligently
        
        # Find score separators
        separator_indices = []
        for i, line in enumerate(box_lines):
            if line == score_separator:
                separator_indices.append(i)
        
        if len(separator_indices) == 2:
            # Extract critical sections
            header = box_lines[:3]  # Top border + 2 info lines
            footer = box_lines[-2:]  # Last status line + bottom border
            
            # Get score section including separators
            score_start = separator_indices[0]
            score_end = separator_indices[1]
            scores = box_lines[score_start:score_end+1]
            
            # Calculate space for middle info and status
            remaining_lines = STANDARD_HEIGHT - len(header) - len(scores) - len(footer)
            
            # Distribute remaining lines - prioritize status over middle info
            status_section = box_lines[score_end+1:-2]
            middle_section = box_lines[3:score_start]
            
            status_lines_to_keep = min(len(status_section), remaining_lines - 1)
            middle_lines_to_keep = remaining_lines - status_lines_to_keep
            
            # Make sure we don't have negative counts
            middle_lines_to_keep = max(0, middle_lines_to_keep)
            status_lines_to_keep = max(0, remaining_lines - middle_lines_to_keep)
            
            # Get the sections to keep
            middle = middle_section[:middle_lines_to_keep]
            status = status_section[:status_lines_to_keep]
            
            # Rebuild the box with exact height
            box_lines = header + middle + scores + status + footer
        else:
            # Fallback - just keep the top and bottom parts
            box_lines = box_lines[:6] + box_lines[-7:]
            
            # If still too long, just force it to standard height
            if len(box_lines) > STANDARD_HEIGHT:
                box_lines = box_lines[:STANDARD_HEIGHT]
    
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
    # Get theme from cookie, default to light
    theme = request.cookies.get("theme", "light")
    print(f"Home route - Current theme: {theme}")
    
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
    
    # Calculate next update time
    next_update_mins = 0
    if next_update_time:
        now = time.time()
        if next_update_time > now:
            next_update_mins = round((next_update_time - now) / 60)
    
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "theme": theme,
        "live_matches": live_matches,
        "completed_matches": completed_matches,
        "upcoming_matches": upcoming_matches,
        "last_updated": cricket_data['last_updated'],
        "time_ago": time_ago,
        "next_update_mins": next_update_mins
    })
    
    # Set appropriate cache control for CDN
    response.headers["Cache-Control"] = f"public, max-age={cache_time}, s-maxage=120"
    
    # Set Vary header to ensure proper caching with cookies
    response.headers["Vary"] = "Cookie"
    
    return response

@app.get("/toggle-theme", response_class=HTMLResponse)
async def toggle_theme(request: Request):
    """Toggle between light and dark theme"""
    # Get current theme from cookie
    current_theme = request.cookies.get("theme", "light")
    
    # Toggle theme
    new_theme = "dark" if current_theme == "light" else "light"
    
    # Get the referer, defaulting to home page
    referer = request.headers.get("referer", "/")
    
    # If referer is the toggle-theme page itself, redirect to home
    if "/toggle-theme" in referer:
        referer = "/"
    
    print(f"Toggle theme - Current: {current_theme}, New: {new_theme}, Referer: {referer}")
    
    # Return a special HTML page that sets the cookie and then redirects
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="0;url={referer}">
        <title>Changing Theme...</title>
    </head>
    <body>
        <p>Changing theme to {new_theme}...</p>
    </body>
    </html>
    """
    
    response = HTMLResponse(content=html_content)
    
    # Set the theme cookie
    response.set_cookie(
        key="theme", 
        value=new_theme, 
        max_age=31536000,  # 1 year
        path="/"
    )
    
    # Set cache control to ensure this page is never cached
    response.headers["Cache-Control"] = "no-store, max-age=0"
    
    return response

@app.get("/test-cookie")
async def test_cookie(request: Request):
    """Test endpoint to check if cookies are working"""
    theme = request.cookies.get("theme", "light")
    return {"current_theme": theme}

@app.get("/plain.txt", response_class=PlainTextResponse)
async def plain_text(request: Request):
    """Serve the cricket scores as plain text, grouped by status"""
    # Get theme from cookie for informational purposes
    theme = request.cookies.get("theme", "light")
    
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
    
    # Add next update info if available
    if next_update_time:
        now = time.time()
        if next_update_time > now:
            next_update_mins = round((next_update_time - now) / 60)
            output.append(f"Next update in approximately {next_update_mins} minutes.")
    
    output.append("Refresh page to update scores.")
    
    # Join all lines and return
    response = PlainTextResponse("\n".join(output))
    
    # Set appropriate cache control for CDN
    response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120"
    
    # Set Vary header to ensure proper caching with cookies
    response.headers["Vary"] = "Cookie"
    
    return response

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    """About page with information about the site"""
    # Get theme from cookie
    theme = request.cookies.get("theme", "light")
    print(f"About route - Current theme: {theme}")
    
    response = templates.TemplateResponse("about.html", {
        "request": request,
        "theme": theme
    })
    
    # Set appropriate cache control for CDN
    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=3600"
    
    # Set Vary header to ensure proper caching with cookies
    response.headers["Vary"] = "Cookie"
    
    return response

async def update_cricket_data():
    """Background task to update cricket data with adaptive interval"""
    global last_cricket_data
    global current_update_interval
    global next_update_time
    
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # Fetch the latest data
            print(f"[{current_time}] Fetching cricket data...")
            cricket_data = fetch_live_scores()
            
            # Calculate next update time based on whether data changed
            if last_cricket_data:
                # Check if data changed
                data_changed = False
                
                # Compare live matches
                prev_live_matches = sum(1 for m in last_cricket_data['matches'] if m['is_live'])
                curr_live_matches = sum(1 for m in cricket_data['matches'] if m['is_live'])
                
                if prev_live_matches != curr_live_matches:
                    data_changed = True
                else:
                    # Check if scores changed for live matches
                    prev_scores = {f"{m['team1']}_{m['team2']}": (m['score1'], m['score2']) 
                                  for m in last_cricket_data['matches'] if m['is_live']}
                    curr_scores = {f"{m['team1']}_{m['team2']}": (m['score1'], m['score2']) 
                                  for m in cricket_data['matches'] if m['is_live']}
                    
                    if prev_scores != curr_scores:
                        data_changed = True
                
                if data_changed:
                    # Reset interval if data changed
                    current_update_interval = 120  # 2 minutes
                else:
                    # Increase interval, with a maximum of 20 minutes
                    current_update_interval = min(current_update_interval * 1.5, 1200)
            
            # Store current data for next comparison
            last_cricket_data = cricket_data
            
            # Set the next update time
            next_update_time = time.time() + current_update_interval
            
            # Log information about the update
            live_matches = sum(1 for m in cricket_data['matches'] if m['is_live'])
            minutes = round(current_update_interval / 60, 1)
            print(f"[{current_time}] Data updated. Found {live_matches} live matches. " +
                  f"Next update in {minutes} minutes.")
            
        except Exception as e:
            print(f"[{current_time}] Error updating cricket data: {e}")
            current_update_interval = 120  # Reset to default on error
            next_update_time = time.time() + current_update_interval
        
        # Wait before updating again
        await asyncio.sleep(current_update_interval)

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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)