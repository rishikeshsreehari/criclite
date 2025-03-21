# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import asyncio
from pathlib import Path
from datetime import datetime
import time
import json
import os
import logging.handlers
import re


from app.data_fetcher import fetch_live_scores, DATA_FILE, DATA_FOLDER, IGNORED_TOURNAMENTS

app = FastAPI()



BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


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


def calculate_time_ago(timestamp):
    """Calculate a human-readable time ago string"""
    seconds_ago = int(time.time() - timestamp)
    
    if seconds_ago < 60:
        return f"{seconds_ago} seconds ago"
    else:
        minutes_ago = seconds_ago // 60
        if minutes_ago == 1:
            return "1 minute ago"
        else:
            return f"{minutes_ago} minutes ago"


def load_cricket_data():
    """Load cricket data from the JSON file and update timestamp values"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Update the timestamps to reflect current time
                current_time = time.time()
                data['current_time'] = current_time
                data['time_ago'] = calculate_time_ago(data.get('last_updated', current_time))
                return data
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
    match_status = match.get('match_status', '')
    start_time_info = match.get('start_time_info', '')
    
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
    
    # Handle different display formats based on match status
    if match_status == "live":
        # Determine which team is batting based on toss/status info 
        # and which has a non-zero score
        batting_team = None
        batting_score = None
        waiting_team = None
        completed_team = None
        completed_score = None
        
        # Check if second innings has begun by looking for targets/runs needed in status
        second_innings_begun = any(phrase in status.lower() for phrase in [
            "need", "require", "target", "to win", "runs to win", "runs from", "chasing"
        ])
        
        if second_innings_begun:
            # For second innings, determine which team is currently batting
            # The team with fewer overs is likely batting now
            overs1 = 0
            overs2 = 0
            if "ov" in score1:
                try:
                    overs1 = float(score1.split("(")[1].split(" ov")[0])
                except:
                    pass
            if "ov" in score2:
                try:
                    overs2 = float(score2.split("(")[1].split(" ov")[0])
                except:
                    pass
            
            if overs1 <= overs2 and score1.strip() != "0/0 (0.0 ov)":
                batting_team = team1
                batting_score = score1
                completed_team = team2
                completed_score = score2
            else:
                batting_team = team2
                batting_score = score2
                completed_team = team1
                completed_score = score1
            
            # Display format: Currently batting team at top
            box_lines.append(f"| {batting_team}  {batting_score.ljust(INNER_WIDTH - len(batting_team) - 2)} |")
            box_lines.append(empty_line)
            box_lines.append(f"| {completed_team}  {completed_score.ljust(INNER_WIDTH - len(completed_team) - 2)} |")
        else:
            # First innings
            if "elected to bat" in status.lower() or "chose to bat" in status.lower():
                # Team that won the toss is batting first
                if team1.lower() in status.lower():
                    batting_team = team1
                    batting_score = score1
                    waiting_team = team2
                else:
                    batting_team = team2
                    batting_score = score2
                    waiting_team = team1
            else:
                # If we can't determine from toss, check which score has actual runs
                score1_has_runs = any(c.isdigit() and c != '0' for c in score1.split('(')[0])
                score2_has_runs = any(c.isdigit() and c != '0' for c in score2.split('(')[0])
                
                if score1_has_runs and not score2_has_runs:
                    batting_team = team1
                    batting_score = score1
                    waiting_team = team2
                elif score2_has_runs and not score1_has_runs:
                    batting_team = team2
                    batting_score = score2
                    waiting_team = team1
                else:
                    # Fallback to original display if can't determine batting team
                    box_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
                    if score1:
                        box_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
                    
                    box_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
                    if score2:
                        box_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
            
            # Use the ESPN-style format for first innings
            if batting_team and waiting_team:
                box_lines.append(f"| {batting_team}  {batting_score.ljust(INNER_WIDTH - len(batting_team) - 2)} |")
                box_lines.append(empty_line)
                box_lines.append(f"| {waiting_team.ljust(INNER_WIDTH)} |")
    else:
        # For non-live matches, use the original display format
        box_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
        if score1:
            box_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
        
        box_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
        if score2:
            box_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
    
    # Add separator before status
    box_lines.append(score_separator)
    
    # For upcoming matches, use start_time_info instead of status if available
    if match_status == "upcoming" and start_time_info:
        status = start_time_info
    
    # Add match status with wrapping - Improved to handle newlines properly
    status_lines = []
    
    # First, split by explicit newlines
    status_parts = status.split('\n')
    for part in status_parts:
        # Then process each part as a wrapped paragraph
        words = part.split()
        current_line = ""
        
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
    
    # Use the pre-calculated time_ago value
    time_ago = cricket_data.get('time_ago', "Unknown time ago")
    
    # Add cache control headers based on data freshness
    seconds_ago = int(time.time() - cricket_data.get('last_updated', time.time()))
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
    
    # Use the pre-calculated time_ago
    time_ago = cricket_data.get('time_ago', "Unknown time ago")
    
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
    output.append(f"Last updated: {cricket_data.get('last_updated_string', 'Unknown')} ({time_ago})")
    
    # Add next update info if available
    now = time.time()
    if NEXT_UPDATE_TIMESTAMP["time"] > now:
        next_update_mins = max(1, round((NEXT_UPDATE_TIMESTAMP["time"] - now) / 60))
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