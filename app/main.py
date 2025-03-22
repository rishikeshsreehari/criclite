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
import logging.handlers

from app.data_fetcher import fetch_live_scores, DATA_FILE, DATA_FOLDER, IGNORED_TOURNAMENTS

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Ensure data directories exist
os.makedirs(DATA_FOLDER, exist_ok=True)

NEXT_UPDATE_TIMESTAMP = {"time": time.time() + 120}


# Set up log file with rotation to prevent it from growing too large
LOG_FILE = DATA_FOLDER / "app_log.txt"
app_logger = logging.getLogger("app")
app_logger.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=1024*1024,  # 1MB file size
    backupCount=3        # Keep 3 backup files
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
app_logger.addHandler(handler)
app_logger.addHandler(logging.StreamHandler())

# Default data structure
default_cricket_data = {
    'last_updated': "Loading...",
    'last_updated_timestamp': time.time(),
    'matches': [],
    'tournaments': []
}

# Store previous data and current interval for adaptive updates
last_cricket_data = None
current_update_interval = 180  # 3 minutes
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
    """Format a match into a consistent ASCII box with fixed borders"""
    
    # Get match data
    match_info = match.get('match_info', '')
    team1 = match.get('team1', '')
    team2 = match.get('team2', '')
    score1 = match.get('score1', '')
    score2 = match.get('score2', '')
    status = match.get('status', '')
    is_live = match.get('is_live', False)
    category = match.get('category', '')
    live_state = match.get('live_state', '').lower()
    description = match.get('description', '')
    
    # Extract date, match number and venue from description
    match_date = ""
    match_number = ""
    venue_info = ""
    
    if description:
        # Try to extract date
        parts = description.split(", ")
        if len(parts) > 1:
            # Last part typically contains date
            date_part = parts[-1]
            if date_part:
                match_date = date_part
        
        # Extract match number
        if ": " in description:
            parts = description.split(": ")
            if len(parts) > 0:
                details = parts[0]
                if "Match" in details or "T20I" in details or "ODI" in details:
                    for part in details.split(", "):
                        if "Match" in part or "T20I" in part or "ODI" in part:
                            match_number = part.strip()
                            break
        
        # Extract venue
        if " at " in description:
            parts = description.split(" at ")
            if len(parts) > 1:
                venue_part = parts[1]
                if ", " in venue_part:
                    venue_info = venue_part.split(", ")[0].strip()
    
    # Determine prefix for match info
    status_prefix = ""
    if is_live:
        status_prefix = "[LIVE] "
    elif live_state == "stumps":
        status_prefix = "[STUMPS] "
    
    # Fixed dimensions
    OUTER_WIDTH = 41
    INNER_WIDTH = 37
    
    # Create box template
    top_border = "+" + "-" * (OUTER_WIDTH - 2) + "+"
    bottom_border = top_border
    empty_line = "| " + " " * INNER_WIDTH + " |"
    score_separator = "|" + "-" * (OUTER_WIDTH - 2) + "|"
    
    # Build the box content
    box_lines = []
    box_lines.append(top_border)
    
    # Format header with date, match number and venue
    header = ""
    if match_date:
        header = match_date
    if match_number:
        if header:
            header += f" - {match_number}"
        else:
            header = match_number
    if venue_info:
        if header:
            header += f" at {venue_info}"
        else:
            header = f"at {venue_info}"
    
    # Add status prefix if needed
    if status_prefix:
        header = status_prefix + header
    
    # Add header with wrapping for long headers
    if header:
        # Split into words and build lines
        words = header.split()
        current_line = ""
        
        for word in words:
            if len(current_line) + len(word) + 1 <= INNER_WIDTH:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                box_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
                current_line = word
                
        if current_line:
            box_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
    
    # Add empty line
    box_lines.append(empty_line)
    
    # Add tournament category with wrapping
    if category:
        words = category.split()
        current_line = ""
        
        for word in words:
            if len(current_line) + len(word) + 1 <= INNER_WIDTH:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                box_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
                current_line = word
                
        if current_line:
            box_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
            
        # Add empty line after category
        box_lines.append(empty_line)
    
    # Add separator before teams/scores
    box_lines.append(score_separator)
    
    # Add team 1 with score
    box_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
    if score1:
        box_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
    
    # Add team 2 with score
    box_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
    if score2:
        box_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
    
    # Add separator before status
    box_lines.append(score_separator)
    
    # Add match status with wrapping
    words = status.split()
    current_line = ""
    status_lines = []
    
    for word in words:
        if len(current_line) + len(word) + 1 <= INNER_WIDTH:
            if current_line:
                current_line += " " + word
            else:
                current_line = word
        else:
            status_lines.append(current_line)
            current_line = word
            
    if current_line:
        status_lines.append(current_line)
    
    for line in status_lines:
        box_lines.append(f"| {line.ljust(INNER_WIDTH)} |")
    
    # Add an empty line if there's space
    if len(box_lines) < 12:  # Assuming we want about 13 lines total with borders
        box_lines.append(empty_line)
    
    # Add bottom border
    box_lines.append(bottom_border)
    
    # Convert to string
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
    
    
    # Load the latest cricket data
    cricket_data = load_cricket_data()
    
    # Calculate how long since the last update
    seconds_ago = int(time.time() - cricket_data.get('last_updated', time.time()))
    
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
    
    for match in cricket_data.get('matches', []):
        # Get match status
        match_status = match.get('match_status', 'unknown') 
        
        formatted_match = format_match_for_display(match)
        
        if match_status == "live":
            live_matches.append(formatted_match)
        elif match_status == "completed":
            completed_matches.append(formatted_match)
        else:  # upcoming or unknown
            upcoming_matches.append(formatted_match)
    
    # Calculate next update time
    next_update_mins = 0
    now = time.time()
    if NEXT_UPDATE_TIMESTAMP["time"] > now:
        next_update_mins = max(1, round((NEXT_UPDATE_TIMESTAMP["time"] - now) / 60))
    
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "theme": theme,
        "live_matches": live_matches,
        "completed_matches": completed_matches,
        "upcoming_matches": upcoming_matches,
        "last_updated": cricket_data.get('last_updated_string', "Unknown"),
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
    
    app_logger.info(f"Toggle theme - Current: {current_theme}, New: {new_theme}, Referer: {referer}")
    
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
    
    for match in cricket_data.get('matches', []):
        # Get match status
        match_status = match.get('match_status', 'unknown')
        
        formatted_match = format_match_for_display(match, use_symbols=False)
        
        if match_status == "live":
            live_matches.append(formatted_match)
        elif match_status == "completed":
            completed_matches.append(formatted_match)
        else:  # upcoming or unknown
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
    output.append(f"Last updated: {cricket_data.get('last_updated_string', 'Unknown')}")
    
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
    app_logger.info(f"About route - Current theme: {theme}")
    
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
    MIN_INTERVAL = 120  # Minimum 2 minutes (in seconds)
    
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.time()
        
        try:
            app_logger.info(f"[{current_time}] Checking for cricket data updates...")
            cricket_data = fetch_live_scores(IGNORED_TOURNAMENTS, logger=app_logger)
            
            # Get info from RSS_FETCH_STRATEGY
            from app.data_fetcher import RSS_FETCH_STRATEGY
            
            wait_index = min(RSS_FETCH_STRATEGY['unchanged_count'], 
                            len(RSS_FETCH_STRATEGY['wait_times']) - 1)
            wait_minutes = RSS_FETCH_STRATEGY['wait_times'][wait_index]
            next_check_seconds = max(MIN_INTERVAL, wait_minutes * 60)
            
            processing_time = time.time() - start_time
            actual_wait_seconds = max(MIN_INTERVAL, next_check_seconds - processing_time)
            
            # Update the timestamp dictionary
            NEXT_UPDATE_TIMESTAMP["time"] = time.time() + actual_wait_seconds
            
            # Log info about the update
            live_matches = sum(1 for m in cricket_data['matches'] if m['is_live'])
            upcoming_matches = sum(1 for m in cricket_data['matches'] if m['match_status'] == 'upcoming')
            
            app_logger.info(f"[{current_time}] Data updated. Found {live_matches} live matches, "
                          f"{upcoming_matches} upcoming matches. Next check in {actual_wait_seconds/60:.1f} minutes.")
            
        except Exception as e:
            app_logger.error(f"[{current_time}] Error updating cricket data: {e}")
            actual_wait_seconds = MIN_INTERVAL
            NEXT_UPDATE_TIMESTAMP["time"] = time.time() + MIN_INTERVAL
        
        # Wait before updating again
        await asyncio.sleep(actual_wait_seconds)

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    # Initial data fetch
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        app_logger.info(f"[{current_time}] Initial data fetch...")
        fetch_live_scores(IGNORED_TOURNAMENTS, logger=app_logger)
        app_logger.info(f"[{current_time}] Initial data loaded")
    except Exception as e:
        app_logger.error(f"[{current_time}] Error fetching initial cricket data: {e}")
    
    # Start background task
    asyncio.create_task(update_cricket_data())

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)