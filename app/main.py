# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import Response, HTMLResponse, PlainTextResponse, RedirectResponse
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
from app.cricket_api_fetcher import fetch_live_scores, DATA_FILE, DATA_FOLDER, IGNORED_TOURNAMENTS
from app.cricket_api_fetcher import fetch_live_scores, load_scorecard, fetch_match_scorecard, clean_old_scorecards, DATA_FILE, DATA_FOLDER, IGNORED_TOURNAMENTS

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

# Config variables for API selection
USE_CRICAPI = True  # Set to True to use CricAPI, False to use ESPNCricinfo
API_ERROR_COUNT = 0  # Track errors to possibly switch APIs
MAX_API_ERRORS = 3  # Switch APIs after this many consecutive errors

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


def format_match_for_display(match, use_symbols=True, include_link=False):
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
    tournament = match.get('tournament', '')
    match_type = match.get('match_type', '')
    match_number = match.get('match_number', '')
    venue = match.get('venue', '')
    match_date = match.get('match_date', '')
    
    # Extract date and venue from description if not directly available
    if not match_date and description:
        # Try to extract date
        parts = description.split(", ")
        if len(parts) > 1:
            match_date = parts[-1]
    
    if not venue and description:
        # Extract venue
        if " at " in description:
            parts = description.split(" at ")
            if len(parts) > 1:
                venue_part = parts[1]
                if ", " in venue_part:
                    venue = venue_part.split(", ")[0].strip()
    
    # Determine prefix for match info
    status_prefix = ""
    if is_live:
        status_prefix = "[LIVE] "
    elif live_state == "stumps":
        status_prefix = "[STUMPS] "
    
    # Fixed dimensions for ALL boxes
    OUTER_WIDTH = 41  # Width including borders (including + characters)
    INNER_WIDTH = 37  # Width excluding borders
    TARGET_CONTENT_LINES = 13  # Target number of lines before view scorecard and bottom border
    
    # Create box template
    top_border = "+" + "-" * (OUTER_WIDTH - 2) + "+"
    bottom_border = top_border
    empty_line = "| " + " " * INNER_WIDTH + " |"
    score_separator = "|" + "-" * (OUTER_WIDTH - 2) + "|"
    
    # Build the content lines (without applying any padding yet)
    content_lines = []
    
    # Add top border
    content_lines.append(top_border)
    
    # Format header with date and venue
    header = ""
    if match_date:
        header = match_date
    if venue:
        if header:
            header += f" at {venue}"
        else:
            header = f"at {venue}"
    
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
                content_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
                current_line = word
                
        if current_line:
            content_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
    
    # Add empty line
    content_lines.append(empty_line)
    
    # Format category line with match type and match number
    category_line = ""
    if match_type:
        category_line = match_type
    if match_number:
        if category_line:
            category_line += f": {match_number}"
        else:
            category_line = match_number
    
    # Add tournament if available
    if tournament:
        if category_line:
            if len(category_line) + len(tournament) + 3 <= INNER_WIDTH:
                category_line += f" - {tournament}"
            else:
                content_lines.append(f"| {category_line.ljust(INNER_WIDTH)} |")
                category_line = tournament
        else:
            category_line = tournament
    
    # Add category/tournament info
    if category_line:
        # Split into words and build lines if needed
        words = category_line.split()
        current_line = ""
        
        for word in words:
            if len(current_line) + len(word) + 1 <= INNER_WIDTH:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                content_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
                current_line = word
                
        if current_line:
            content_lines.append(f"| {current_line.ljust(INNER_WIDTH)} |")
            
        # Add empty line after category
        content_lines.append(empty_line)
    
    # Add separator before teams/scores
    content_lines.append(score_separator)
    
    # Handle different display formats based on match status
    team_score_lines = []
    
    # Check specifically for Test match with multiple innings
    is_test_match = match_type and match_type.upper() == "TEST"
    has_multiple_innings = "&" in score1 or "&" in score2
    
    if is_test_match and has_multiple_innings:
        # Special handling for Test matches with multiple innings
        team_score_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
        if score1:
            team_score_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
        
        team_score_lines.append(empty_line)
        
        team_score_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
        if score2:
            team_score_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
    elif match_status == "live":
        # Improved logic for determining batting team in live matches
        batting_team = None
        batting_score = None
        waiting_team = None
        completed_team = None
        completed_score = None
        
        # First, check which team has a non-empty score
        if score1 and not score2:
            batting_team = team1
            batting_score = score1
            waiting_team = team2
        elif score2 and not score1:
            batting_team = team2
            batting_score = score2
            waiting_team = team1
        # Check for second innings (both teams have scores)
        elif score1 and score2:
            # Check for keywords in status indicating second innings
            second_innings_begun = any(phrase in status.lower() for phrase in [
                "need", "require", "target", "to win", "runs to win", "runs from", "chasing"
            ])
            
            if second_innings_begun:
                # Determine which team is currently batting by checking overs
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
                team_score_lines.append(f"| {batting_team}  {batting_score.ljust(INNER_WIDTH - len(batting_team) - 2)} |")
                team_score_lines.append(empty_line)
                team_score_lines.append(f"| {completed_team}  {completed_score.ljust(INNER_WIDTH - len(completed_team) - 2)} |")
            else:
                # First innings with both teams having some score
                # Check toss information
                if any(phrase in status.lower() for phrase in ["elected to bat", "chose to bat", "opt to bat", "to bowl"]):
                    # Try to determine from status text
                    if "to bowl" in status.lower():
                        # Team opting to bowl bats second - check which team opted to bowl
                        team1_in_status = team1.lower() in status.lower()
                        team2_in_status = team2.lower() in status.lower()
                        
                        if team1_in_status and not team2_in_status:
                            batting_team = team2
                            batting_score = score2
                            waiting_team = team1
                        elif team2_in_status and not team1_in_status:
                            batting_team = team1
                            batting_score = score1
                            waiting_team = team2
                        else:
                            # If can't determine clearly, use the team with more runs
                            score1_runs = int(score1.split('/')[0]) if score1 and '/' in score1 else 0
                            score2_runs = int(score2.split('/')[0]) if score2 and '/' in score2 else 0
                            
                            if score1_runs >= score2_runs:
                                batting_team = team1
                                batting_score = score1
                                waiting_team = team2
                            else:
                                batting_team = team2
                                batting_score = score2
                                waiting_team = team1
                    else:
                        # Team opting to bat bats first
                        team1_in_status = team1.lower() in status.lower()
                        team2_in_status = team2.lower() in status.lower()
                        
                        if team1_in_status and not team2_in_status:
                            batting_team = team1
                            batting_score = score1
                            waiting_team = team2
                        elif team2_in_status and not team1_in_status:
                            batting_team = team2
                            batting_score = score2
                            waiting_team = team1
                        else:
                            # If can't determine clearly, use the team with more runs
                            score1_runs = int(score1.split('/')[0]) if score1 and '/' in score1 else 0
                            score2_runs = int(score2.split('/')[0]) if score2 and '/' in score2 else 0
                            
                            if score1_runs >= score2_runs:
                                batting_team = team1
                                batting_score = score1
                                waiting_team = team2
                            else:
                                batting_team = team2
                                batting_score = score2
                                waiting_team = team1
                else:
                    # No clear toss info, check which score has more runs
                    score1_runs = int(score1.split('/')[0]) if score1 and '/' in score1 else 0
                    score2_runs = int(score2.split('/')[0]) if score2 and '/' in score2 else 0
                    
                    if score1_runs >= score2_runs:
                        batting_team = team1
                        batting_score = score1
                        waiting_team = team2
                    else:
                        batting_team = team2
                        batting_score = score2
                        waiting_team = team1
                
                # Display the determined teams
                team_score_lines.append(f"| {batting_team}  {batting_score.ljust(INNER_WIDTH - len(batting_team) - 2)} |")
                team_score_lines.append(empty_line)
                team_score_lines.append(f"| {waiting_team.ljust(INNER_WIDTH)} |")
        else:
            # No scores yet, just show team names
            team_score_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
            team_score_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
            
        # If we still haven't determined teams (fallback)
        if not team_score_lines:
            team_score_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
            if score1:
                team_score_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
            
            team_score_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
            if score2:
                team_score_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
    else:
        # For non-live matches, use the original display format
        team_score_lines.append(f"| {team1.ljust(INNER_WIDTH)} |")
        if score1:
            team_score_lines.append(f"| {score1.ljust(INNER_WIDTH)} |")
        
        team_score_lines.append(f"| {team2.ljust(INNER_WIDTH)} |")
        if score2:
            team_score_lines.append(f"| {score2.ljust(INNER_WIDTH)} |")
    
    # Add the team/score lines
    content_lines.extend(team_score_lines)
    
    # Add separator before status
    content_lines.append(score_separator)
    
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
    
    # Add the status lines
    for line in status_lines:
        content_lines.append(f"| {line.ljust(INNER_WIDTH)} |")
    
    # Calculate how many empty lines to add to reach TARGET_CONTENT_LINES
    empty_lines_needed = TARGET_CONTENT_LINES - len(content_lines)
    
    # Add empty lines to make all content boxes the same height
    for _ in range(max(0, empty_lines_needed)):
        content_lines.append(empty_line)
    
    # Now all boxes have exactly TARGET_CONTENT_LINES lines
    
    # Add "View Scorecard" link inside the box if requested
    if include_link:
        # Add a separator before the link
        content_lines.append(score_separator)
        
        # Add "View Scorecard" centered in the box
        link_text = "Scorecard"
        padding = (INNER_WIDTH - len(link_text)) // 2
        content_lines.append(f"| {' ' * padding}{link_text}{' ' * (INNER_WIDTH - padding - len(link_text))} |")
    
    # Add bottom border
    content_lines.append(bottom_border)
    
    # Convert to string and return
    return "\n".join(content_lines)

def format_scorecard_as_html(scorecard_data, match_info, scorecard_file_data=None, show_second_innings_first=True):
    """Format scorecard data with improved ASCII layout and concise match summary"""
    if not scorecard_data:
        return "<div class='no-data'>Scorecard data not available</div>"
    
    html = []
    html.append("<div class='scorecard-container'>")
    
    # Extract match details
    match_name = scorecard_data.get('name', 'Match Scorecard')
    venue = scorecard_data.get('venue', '')
    date = scorecard_data.get('date', '')
    status = scorecard_data.get('status', '')
    tournament = match_info.get('tournament', 'Cricket Match')
    match_number = match_info.get('match_number', '')
    match_type = match_info.get('match_type', '')
    team1 = match_info.get('team1', '')
    team2 = match_info.get('team2', '')
    score1 = match_info.get('score1', '')
    score2 = match_info.get('score2', '')
    match_status = match_info.get('status', '')
    
    # Define column widths for scorecard tables
    batter_width = 35
    dismissal_width = 35
    stat_width = 6  # For R, B, 4s, 6s
    sr_width = 8    # For strike rate
    
    # Calculate the actual width needed for batting scorecard
    # Batsman(35) + Dismissal(35) + R(6) + B(6) + 4s(6) + 6s(6) + SR(8)
    actual_width = batter_width + dismissal_width + (stat_width * 4) + sr_width
    
    # Use exactly this width for everything
    width = actual_width
    
    # Create ASCII-style match header box with the exact same width
    html.append("<pre class='ascii-box'>")
    html.append("+" + "-" * (width - 2) + "+")
    
    # First line - match info
    if match_number:
        header_text = f"[LIVE] {match_number}, {venue}, {date}, {tournament}"
    else:
        header_text = f"[LIVE] {venue}, {date}, {tournament}"
    
    # Handle long header text with wrapping
    if len(header_text) > width - 4:
        words = header_text.split()
        current_line = "| "
        for word in words:
            if len(current_line) + len(word) + 1 <= width - 2:
                current_line += word + " "
            else:
                html.append(current_line.ljust(width - 1) + "|")
                current_line = "| " + word + " "
        if current_line != "| ":
            html.append(current_line.ljust(width - 1) + "|")
    else:
        padded_text = f"| {header_text.ljust(width - 4)} |"
        html.append(padded_text)
    
    # Separator
    html.append("|" + "-" * (width - 2) + "|")
    html.append(f"| {' '.ljust(width - 4)} |")  # Empty line
    
    # Determine match stage and display scores accordingly
    if "need" in match_status.lower() and "runs" in match_status.lower():
        # This is a chase - determine which team is batting
        chasing_team = None
        defending_team = None
        chasing_score = None
        defending_score = None
        
        if team1.lower() in match_status.lower():
            chasing_team = team1
            chasing_score = score1
            defending_team = team2
            defending_score = score2
        else:
            chasing_team = team2
            chasing_score = score2
            defending_team = team1
            defending_score = score1
        
        # Show defending team first, then chasing team - ensure full width alignment
        if defending_team and defending_score:
            team_score = f"{defending_team} {defending_score}"
            html.append(f"| {team_score.ljust(width - 4)} |")
        if chasing_team and chasing_score:
            team_score = f"{chasing_team} {chasing_score}"
            html.append(f"| {team_score.ljust(width - 4)} |")
    else:
        # Regular match - just show teams in order - ensure full width alignment
        team_score1 = f"{team1} {score1}"
        html.append(f"| {team_score1.ljust(width - 4)} |")
        team_score2 = f"{team2} {score2}"
        html.append(f"| {team_score2.ljust(width - 4)} |")
    
    # Separator
    html.append("|" + "-" * (width - 2) + "|")
    
    # Match status with wrapping if needed
    status_text = match_status
    if len(status_text) > width - 4:
        words = status_text.split()
        current_line = "| "
        for word in words:
            if len(current_line) + len(word) + 1 <= width - 2:
                current_line += word + " "
            else:
                html.append(current_line.ljust(width - 1) + "|")
                current_line = "| " + word + " "
        if current_line != "| ":
            html.append(current_line.ljust(width - 1) + "|")
    else:
        html.append(f"| {status_text.ljust(width - 4)} |")
    
    # Now add the concise summary section if match is live
    if match_info.get('match_status') == 'live':
        # Determine batting team
        batting_team = None
        bowling_team = None
        current_innings = None
        
        # Find the current innings data
        for inning in scorecard_data.get('scorecard', []):
            inning_name = inning.get('inning', '').lower()
            if team1.lower() in inning_name and score1:
                batting_team = team1
                bowling_team = team2
                current_innings = inning
                break
            elif team2.lower() in inning_name and score2:
                batting_team = team2
                bowling_team = team1
                current_innings = inning
                break
        
        # If we found current innings, show summary
        if current_innings:
            html.append("|" + "-" * (width - 2) + "|")  # Separator
            
            # Batters table header - simplified version with proper alignment
            header_batsman = "Batsman".ljust(batter_width)
            header_r = "R".rjust(stat_width)
            header_b = "B".rjust(stat_width)
            header_4s = "4s".rjust(stat_width)
            header_6s = "6s".rjust(stat_width)
            header_sr = "SR".rjust(sr_width)
            
            # Calculate total width of all columns to ensure perfect alignment
            total_header_width = len(header_batsman) + len(header_r) + len(header_b) + len(header_4s) + len(header_6s) + len(header_sr)
            padding_needed = width - 4 - total_header_width  # -4 for the "| " and " |" on each end
            
            # Add any needed padding to the SR column
            if padding_needed > 0:
                header_sr = header_sr + " " * padding_needed
            
            # Add the header row with exact alignment
            html.append(f"| {header_batsman}{header_r}{header_b}{header_4s}{header_6s}{header_sr} |")
            html.append("|" + "-" * (width - 2) + "|")  # Separator
            
            # Find current batters
            current_batters = []
            for batsman in current_innings.get('batting', []):
                dismissal_raw = batsman.get('dismissal-text', '').lower()
                if dismissal_raw == 'batting' or dismissal_raw == 'not out':
                    name = batsman.get('batsman', {}).get('name', '')
                    name = name.title() # To Capitalize the name
                    runs = batsman.get('r', 0)
                    balls = batsman.get('b', 0)
                    fours = batsman.get('4s', 0)
                    sixes = batsman.get('6s', 0)
                    strike_rate = batsman.get('sr', 0)
                    
                    # Format name with asterisk for current batsman
                    name_display = f"{name}*"
                    
                    # Format line with fixed widths (no dismissal column in summary)
                    current_batters.append({
                        'name': name_display,
                        'r': runs,
                        'b': balls,
                        '4s': fours,
                        '6s': sixes,
                        'sr': strike_rate
                    })
            
            # Show current batters
            for batter in current_batters:
                name_col = batter['name'].ljust(batter_width)
                r_col = str(batter['r']).rjust(stat_width)
                b_col = str(batter['b']).rjust(stat_width)
                fours_col = str(batter['4s']).rjust(stat_width)
                sixes_col = str(batter['6s']).rjust(stat_width)
                sr_col = str(round(batter['sr'], 2)).rjust(sr_width)
                
                # Add the same padding to the SR column for consistent alignment
                if padding_needed > 0:
                    sr_col = sr_col + " " * padding_needed
                
                # Add the perfectly aligned batter row
                html.append(f"| {name_col}{r_col}{b_col}{fours_col}{sixes_col}{sr_col} |")
            
            html.append(f"| {' '.ljust(width - 4)} |")  # Empty line
            
            # Find current bowler
            bowling_innings = None
            for inning in scorecard_data.get('scorecard', []):
                if bowling_team and bowling_team.lower() in inning.get('inning', '').lower():
                    bowling_innings = inning
                    break
            
            if bowling_innings:
                # Find current bowler (last active)
                bowlers = bowling_innings.get('bowling', [])
                current_bowler = None
                
                if bowlers:
                    # Try to find bowler with incomplete over first
                    decimal_overs = []
                    for bowler in bowlers:
                        overs_str = str(bowler.get('o', '0'))
                        if '.' in overs_str:
                            decimal_overs.append(bowler)
                    
                    # Use bowler with decimal overs if found, otherwise use lowest overs
                    if decimal_overs:
                        current_bowler = decimal_overs[0]
                    else:
                        # Sort by total overs
                        sorted_bowlers = sorted(bowlers, key=lambda x: float(str(x.get('o', '0')).replace('-', '.')))
                        current_bowler = sorted_bowlers[0] if sorted_bowlers else None
                
                if current_bowler:
                    name = current_bowler.get('bowler', {}).get('name', '')
                    name = name.title() # To Capitalize the name
                    overs = current_bowler.get('o', 0)
                    maidens = current_bowler.get('m', 0)
                    runs = current_bowler.get('r', 0)
                    wickets = current_bowler.get('w', 0)
                    econ = current_bowler.get('eco', 0)
                    
                    # Format current bowler line
                    bowler_text = f"{name}: {overs}-{maidens}-{runs}-{wickets} (Econ: {econ})"
                    html.append(f"| {bowler_text.ljust(width - 4)} |")
            
            # Find last dismissal
            last_dismissal = ""
            for batsman in current_innings.get('batting', []):
                dismissal_raw = batsman.get('dismissal-text', '').lower()
                dismissal = ' '.join(word.capitalize() if word.lower() not in ['b', 'c', 'lbw', 'run', 'out','st','hit','wicket','retired','hurt','timed','obstructing','the'
                'field','handled','ball', 'not'] else word.lower()
                     for word in dismissal_raw.split())
                if dismissal and dismissal.lower() != 'batting' and dismissal.lower() != 'not out':
                    name = batsman.get('batsman', {}).get('name', '')
                    name = name.title() # To Capitalize the name
                    runs = batsman.get('r', 0)
                    balls = batsman.get('b', 0)
                    last_dismissal = f"Last Dismissal: {name} {runs}({balls}b)"
                    break
            
            if last_dismissal:
                html.append(f"| {last_dismissal.ljust(width - 4)} |")
                
            # DRS info
            html.append("|" + "-" * (width - 2) + "|")  # Separator
            
            # Get team names from the actual match data
            match_teams = scorecard_data.get('teams', [team1, team2])
            if len(match_teams) < 2:
                match_teams = [team1, team2]  # Fallback to match_info if needed
            
            team1_name = match_teams[0] if len(match_teams) > 0 else "Team 1"
            team2_name = match_teams[1] if len(match_teams) > 1 else "Team 2"
            
            drs_text = f"Reviews Remaining: {team1_name} - 2 of 2, {team2_name} - 2 of 2"
            html.append(f"| {drs_text.ljust(width - 4)} |")
    
    # Close the box - remove the empty line at the bottom
    html.append("+" + "-" * (width - 2) + "+")
    html.append("</pre>")
    
    html.append("<br>")  # Single line break for minimal spacing

    
    # Rest of the function remains the same - process innings data
    scorecard_innings = scorecard_data.get('scorecard', [])
    
    # Determine which innings to show first
    if show_second_innings_first and len(scorecard_innings) > 1:
        innings_order = list(range(len(scorecard_innings)))
        # Put the last innings first
        innings_order = [innings_order[-1]] + innings_order[:-1]
    else:
        innings_order = range(len(scorecard_innings))
    
    for idx in innings_order:
        if idx >= len(scorecard_innings):
            continue
            
        inning_data = scorecard_innings[idx]
        inning_name = inning_data.get('inning', '')
        is_current_innings = idx == innings_order[0]
        
        if inning_name:
            html.append("<div class='innings-section'>")
            
            # Extract team name from inning name
            team_name = inning_name.split(" Inning")[0]
            
            # Create a centered team name header with dashes
            html.append("<pre class='ascii-innings-header'>")
            html.append("")
            centered_innings = f" {team_name} "
            padding = "-" * ((width - len(centered_innings)) // 2)
            remaining_padding = width - len(padding) * 2 - len(centered_innings)
            html.append(padding + centered_innings + padding + ("-" * remaining_padding))
            html.append("</pre>")
            
            # Add batting section
            html.append("<pre class='ascii-section-header'>")
            html.append("")
            html.append("BATTING")
            html.append("-" * width)  # Full width divider
            
            # Header for batting table - with fixed column widths
            header = f"{'Batsman'.ljust(batter_width)}{'Dismissal'.ljust(dismissal_width)}{'R'.rjust(stat_width)}{'B'.rjust(stat_width)}{'4s'.rjust(stat_width)}{'6s'.rjust(stat_width)}{'SR'.rjust(sr_width)}"
            html.append(header)
            html.append("-" * width)  # Full width divider
            
            # Add each batsman with fixed width formatting
            batting = inning_data.get('batting', [])
            last_dismissal = ""
            
            for batsman in batting:
                name = batsman.get('batsman', {}).get('name', '')
                name = name.title() # To Capitalize the name
                dismissal_raw = batsman.get('dismissal-text', '')
                
                if dismissal_raw.lower() == 'batting' or dismissal_raw.lower() == 'not out':
                    # Always use "not out" with lowercase 'not'
                    dismissal = 'not out'
                else:
                    # Apply formatting to other dismissal types
                    dismissal = ' '.join(
                        word.capitalize() if word.lower() not in ['b', 'c', 'lbw', 'run', 'out','st','hit','wicket','retired','hurt','timed','obstructing','the','field','handled','ball']
                        else word.lower()
                        for word in dismissal_raw.split()
                    )
                
                # Store last dismissal for "Last Bat" info
                if dismissal_raw and dismissal_raw.lower() not in ["batting", "not out"]:
                    last_dismissal = f"{name} {batsman.get('r', 0)} ({batsman.get('b', 0)}b)"
                
                # Format name for batting players
                name_display = name
                if dismissal_raw.lower() == 'batting' or dismissal_raw.lower() == 'not out':
                    name_display = f"{name}*"
                
                runs = batsman.get('r', 0)
                balls = batsman.get('b', 0)
                fours = batsman.get('4s', 0)
                sixes = batsman.get('6s', 0)
                strike_rate = batsman.get('sr', 0)
                
                # Skip players who haven't batted yet
                if runs == 0 and balls == 0 and dismissal.lower() != "not out" and dismissal_raw.lower() != "batting":
                    continue
                
                # Format line with fixed widths
                line = f"{name_display[:batter_width].ljust(batter_width)}{dismissal[:dismissal_width].ljust(dismissal_width)}{str(runs).rjust(stat_width)}{str(balls).rjust(stat_width)}{str(fours).rjust(stat_width)}{str(sixes).rjust(stat_width)}{str(round(strike_rate, 2)).rjust(sr_width)}"
                html.append(line)
            
            # Add extras if available
            extras = inning_data.get('extras', {}).get('r', 0)
            if extras:
                # Format extras line with proper alignment and visual distinction
                extras_line = f"{'Extras (b, lb, w, nb, p)'.ljust(batter_width)}{' '.ljust(dismissal_width)}{str(extras).rjust(stat_width)}"
                # Calculate padding needed to fill the full width
                padding_needed = width - len(extras_line)
                if padding_needed > 0:
                    extras_line += " " * padding_needed
                # Add a blank line before extras for separation
                html.append("")
                html.append(extras_line)
            
            # Add divider line before total
            html.append("-" * width)
            
            # Calculate and add total with run rate
            total_runs = sum(batsman.get('r', 0) for batsman in batting) + extras
            total_wickets = sum(1 for batsman in batting if batsman.get('dismissal-text', '').lower() not in ['not out', 'batting'])
            
            # Get total overs
            total_overs = 0
            score_entries = scorecard_data.get('score', [])
            for score_entry in score_entries:
                if inning_name in score_entry.get('inning', ''):
                    total_overs = score_entry.get('o', 0)
                    break
                    
            # If not found, calculate from bowling data
            if not total_overs:
                bowling = inning_data.get('bowling', [])
                max_overs = 0
                for bowler in bowling:
                    bowler_overs = bowler.get('o', 0)
                    try:
                        if isinstance(bowler_overs, str) and '.' in bowler_overs:
                            over_parts = bowler_overs.split('.')
                            bowler_overs = float(over_parts[0]) + float(over_parts[1])/6
                        max_overs = max(max_overs, float(bowler_overs))
                    except (ValueError, TypeError):
                        pass
                total_overs = max_overs
            
            # Calculate run rate
            run_rate = 0
            if total_overs:
                try:
                    run_rate = total_runs / float(total_overs)
                except (ValueError, TypeError):
                    pass
            
            # Format the total line with proper formatting and spacing
            score_display = f"{total_runs}/{total_wickets}"
            
            if match_type and match_type.lower() == 't20':
                # For T20 matches with run rate display
                left_part = f"<strong>TOTAL</strong>      {total_overs} Ov (RR: {run_rate:.2f})"
                right_part = f"<strong>{score_display}</strong>"
                # Calculate spacing to align the score at the right
                padding_needed = width - len(left_part.replace("<strong>", "").replace("</strong>", "")) - len(right_part.replace("<strong>", "").replace("</strong>", ""))
                total_text = left_part + " " * padding_needed + right_part
            else:
                # For Test/ODI matches
                left_part = f"<strong>TOTAL</strong>          ({total_wickets} wickets)"
                right_part = f"<strong>{total_runs}</strong>"
                padding_needed = width - len(left_part.replace("<strong>", "").replace("</strong>", "")) - len(right_part.replace("<strong>", "").replace("</strong>", ""))
                total_text = left_part + " " * padding_needed + right_part
            
            html.append(total_text)
            
            # Add Last Bat and FOW if it's current innings
            if is_current_innings and last_dismissal:
                html.append("")
                html.append(f"Last Bat: {last_dismissal} • FOW: {score_display}")
            
            # Add bowling section
            html.append("")
            html.append("BOWLING")
            html.append("-" * width)
            
            # Header for bowling table - with fixed column widths
            bowler_width = 35
            stat_width = 6
            wide_stat = 7
            # Calculate the proper formatting to match the total width
            remaining_width = width - bowler_width - (stat_width * 6) - wide_stat
            bowling_header = f"{'Bowler'.ljust(bowler_width)}{'O'.rjust(stat_width)}{'M'.rjust(stat_width)}{'R'.rjust(stat_width)}{'W'.rjust(stat_width)}{'NB'.rjust(stat_width)}{'WD'.rjust(stat_width)}{'Econ'.rjust(wide_stat)}"
            
            # Add padding if needed to match the total width
            if len(bowling_header) < width:
                bowling_header = bowling_header + " " * (width - len(bowling_header))
            
            html.append(bowling_header)
            html.append("-" * width)
            
            # Add each bowler with fixed width formatting
            bowling = inning_data.get('bowling', [])
            for bowler in bowling:
                name = bowler.get('bowler', {}).get('name', '')
                name = ' '.join(word.capitalize() for word in name.split())
                # name = name.title() # To Capitalize the name
                overs = bowler.get('o', 0)
                maidens = bowler.get('m', 0)
                runs = bowler.get('r', 0)
                wickets = bowler.get('w', 0)
                no_balls = bowler.get('nb', 0)
                wides = bowler.get('wd', 0)
                economy = bowler.get('eco', 0)
                
                bowler_line = f"{name[:bowler_width].ljust(bowler_width)}{str(overs).rjust(stat_width)}{str(maidens).rjust(stat_width)}{str(runs).rjust(stat_width)}{str(wickets).rjust(stat_width)}{str(no_balls).rjust(stat_width)}{str(wides).rjust(stat_width)}{str(round(economy, 2)).rjust(wide_stat)}"
                
                # Add padding if needed to match the total width
                if len(bowler_line) < width:
                    bowler_line = bowler_line + " " * (width - len(bowler_line))
                    
                html.append(bowler_line)
            
            html.append("</pre>")
            html.append("</div>")  # End of innings section
    
    # Add DRS info with matching width for the detailed scorecard
    if not match_info.get('match_status') == 'live':  # Only show if not already shown in summary
        html.append("<pre class='ascii-drs-info'>")
        html.append("-" * width)
        
        # Get team names from the actual match data
        match_teams = scorecard_data.get('teams', [team1, team2])
        if len(match_teams) < 2:
            match_teams = [team1, team2]  # Fallback to match_info if needed
        
        team1_name = match_teams[0] if len(match_teams) > 0 else "Team 1"
        team2_name = match_teams[1] if len(match_teams) > 1 else "Team 2"
        
        html.append(f"Reviews Remaining: {team1_name} - 2 of 2, {team2_name} - 2 of 2")
        html.append("-" * width)
        html.append("</pre>")
    
    # Add last updated info
    current_time = time.time()
    
    # Get the timestamp from the scorecard file data if available, otherwise fall back to match_info
    last_updated_string = None
    last_updated_timestamp = None
    
    if scorecard_file_data and 'last_updated_string' in scorecard_file_data:
        last_updated_string = scorecard_file_data.get('last_updated_string')
        last_updated_timestamp = scorecard_file_data.get('last_updated')
    else:
        last_updated_string = match_info.get('last_updated_string', datetime.now().strftime("%Y-%m-%d %H:%M:%S GMT"))
        last_updated_timestamp = match_info.get('last_updated', current_time)
    
    # Calculate time ago
    time_ago = "just now"
    seconds_ago = int(current_time - last_updated_timestamp)
    
    if seconds_ago < 60:
        time_ago = f"{seconds_ago} seconds ago"
    else:
        minutes_ago = seconds_ago // 60
        if minutes_ago == 1:
            time_ago = "1 minute ago"
        else:
            time_ago = f"{minutes_ago} minutes ago"
    
    html.append(f"Last updated: {last_updated_string} ({time_ago})")
    html.append("<br>")  # Add a blank line for spacing
    html.append("Page auto-refreshes every 30s")
    
    html.append("</div>")  # End of scorecard container
    
    return "\n".join(html)


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
    
    # Simplify cache control - always use 30 seconds for browser cache
    cache_time = 30
    
    # Group matches by status with match IDs
    live_matches = []
    completed_matches = []
    
    # Store upcoming matches with their timestamps for sorting
    upcoming_matches_with_time = []
    
    # Current date for filtering
    current_date = datetime.now().date()
    
    # First pass: collect all matches to determine consistent dimensions
    all_matches = []
    for match in cricket_data.get('matches', []):
        # Get match status and ID
        match_status = match.get('match_status', 'unknown')
        match_id = match.get('match_id', '')
        
        # Filter out old completed matches
        if match_status == "completed":
            match_date_str = match.get('match_date')
            if match_date_str:
                try:
                    match_date = datetime.strptime(match_date_str, "%Y-%m-%d").date()
                    days_old = (current_date - match_date).days
                    if days_old > 2:  # Skip matches older than 2 days
                        continue
                except:
                    pass  # If date parsing fails, include the match
        
        all_matches.append(match)
    
    # Format all matches with consistent formatting
    for match in all_matches:
        match_status = match.get('match_status', 'unknown')
        match_id = match.get('match_id', '')
        
        # Only include scorecard link for live or completed matches, not upcoming
        include_link = match_status in ["live", "completed"]
        
        # Format the match with or without the scorecard link
        formatted_match = format_match_for_display(match, include_link=include_link)
        
        if match_status == "completed":
            completed_matches.append((match_id, formatted_match))
        elif match_status == "live":
            live_matches.append((match_id, formatted_match))
        else:  # upcoming or unknown
            match_time = match.get('match_time', float('inf'))
            upcoming_matches_with_time.append((match_time, match_id, formatted_match))
    
    # Sort upcoming matches by match_time (earliest first)
    upcoming_matches_with_time.sort(key=lambda x: x[0])
    
    # Extract just the formatted matches in sorted order with match IDs
    upcoming_matches = [(match_id, formatted_match) for _, match_id, formatted_match in upcoming_matches_with_time]
    
    # Calculate next update time with seconds
    next_update_text = ""
    now = time.time()
    if NEXT_UPDATE_TIMESTAMP["time"] > now:
        time_diff = NEXT_UPDATE_TIMESTAMP["time"] - now
        if time_diff < 60:
            next_update_text = f"{int(time_diff)} seconds"
        else:
            minutes = int(time_diff // 60)
            seconds = int(time_diff % 60)
            next_update_text = f"{minutes} minute{'s' if minutes > 1 else ''} and {seconds} seconds"
    
    response = templates.TemplateResponse("index.html", {
        "request": request,
        "theme": theme,
        "live_matches": live_matches,
        "completed_matches": completed_matches,
        "upcoming_matches": upcoming_matches,
        "last_updated": cricket_data.get('last_updated_string', "Unknown"),
        "time_ago": time_ago,
        "next_update_text": next_update_text
    })
    
    # Set appropriate cache control for CDN
    response.headers["Cache-Control"] = f"public, max-age={cache_time}, s-maxage=60"
    
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
    
    # Current date for filtering
    current_date = datetime.now().date()
    
    for match in cricket_data.get('matches', []):
        # Get match status
        match_status = match.get('match_status', 'unknown')
        
        # Filter out old completed matches
        if match_status == "completed":
            match_date_str = match.get('match_date')
            if match_date_str:
                try:
                    match_date = datetime.strptime(match_date_str, "%Y-%m-%d").date()
                    days_old = (current_date - match_date).days
                    if days_old > 2:  # Skip matches older than 2 days
                        continue
                except:
                    pass  # If date parsing fails, include the match
        
        # Format without the scorecard link for plain text output
        formatted_match = format_match_for_display(match, use_symbols=False, include_link=False)
        
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
    
    output.append("Refresh page to update scores.")
    
    # Join all lines and return
    response = PlainTextResponse("\n".join(output))
    
    # Set appropriate cache control for CDN
    response.headers["Cache-Control"] = "public, max-age=30, s-maxage=60"
    
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


@app.get("/api/status", response_class=HTMLResponse)
async def api_status(request: Request):
    """Return simple API status information"""
    try:
        # Load the latest cricket data
        cricket_data = load_cricket_data()
        
        # Get basic stats
        match_count = len(cricket_data.get('matches', []))
        live_count = sum(1 for m in cricket_data.get('matches', []) if m.get('match_status') == 'live')
        time_ago = cricket_data.get('time_ago', "Unknown")
        data_source = "CricAPI" if USE_CRICAPI else "ESPNCricinfo"
        
        # Format a simple status message
        status_html = f"""
        <!DOCTYPE html>
        <html>
        <head><title>CricLite API Status</title></head>
        <body>
            <h1>CricLite API Status</h1>
            <p>Status: Online</p>
            <p>Data Source: {data_source}</p>
            <p>Last Updated: {time_ago}</p>
            <p>Match Count: {match_count} ({live_count} live)</p>
            <p>Next Update: {round((NEXT_UPDATE_TIMESTAMP["time"] - time.time()) / 60)} minutes</p>
        </body>
        </html>
        """
        
        return HTMLResponse(content=status_html)
    except Exception as e:
        return HTMLResponse(content=f"Error: {str(e)}", status_code=500)


#Function to periodically check for upcoming matches and live score
# In main.py, update the update_cricket_data function:

async def update_cricket_data():
    """Background task to update cricket data with adaptive intervals based on data changes"""
    MIN_INTERVAL = 60  # Start with 1-minute interval (in seconds)
    MAX_INTERVAL = 600  # Maximum 10-minute interval (in seconds)
    UPCOMING_CHECK_INTERVAL = 3600  # Check for upcoming matches every hour (in seconds)
    SCORECARD_INTERVAL = 120  # Check for scorecard updates every 2 minutes (in seconds)
    
    # Track consecutive updates with no changes
    no_change_count = 0
    scorecard_update_count = 0
    current_interval = MIN_INTERVAL
    last_data_hash = None
    last_upcoming_check = 0
    last_scorecard_update = 0
    scorecard_update_times = {}  # Track last update time per match
    completed_match_update_counts = {}  # Track update count for completed matches
    consecutive_failures = 0
    
    while True:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.time()
        
        try:
            app_logger.info(f"[{current_time}] Checking for cricket data updates...")
            
            cricket_data = None
            
            # Try to fetch live scores (this already includes upcoming matches in the latest version)
            try:
                app_logger.info("Fetching from CricAPI...")
                cricket_data = fetch_live_scores(IGNORED_TOURNAMENTS, logger=app_logger)
                
                if cricket_data and len(cricket_data.get('matches', [])) > 0:
                    app_logger.info(f"Successfully fetched data with {len(cricket_data['matches'])} matches")
                    consecutive_failures = 0  # Reset failure counter
                else:
                    app_logger.warning(f"API returned no matches")
                    cricket_data = None
                    consecutive_failures += 1
            except Exception as e:
                app_logger.error(f"Error with API: {str(e)}")
                cricket_data = None
                consecutive_failures += 1
            
            # If API fails too many times in succession, restart the service
            if consecutive_failures >= 5:
                app_logger.critical("5 consecutive API failures. Attempting to restart service...")
                try:
                    # First save the current state before restarting
                    if os.path.exists(DATA_FILE):
                        backup_path = DATA_FILE.with_suffix('.backup.json')
                        import shutil
                        shutil.copy2(DATA_FILE, backup_path)
                        app_logger.info(f"Backed up data file to {backup_path}")
                        
                    # Attempt to restart the service
                    result = restart_service(app_logger)
                    if result:
                        app_logger.info("Service restart command successful")
                    else:
                        app_logger.error("Service restart command failed")
                except Exception as restart_error:
                    app_logger.error(f"Error during restart attempt: {str(restart_error)}")
                    
                # Reset the counter regardless of restart success
                consecutive_failures = 0
                
                # Wait longer before continuing
                await asyncio.sleep(60)
                continue
            
            # If we couldn't get data, wait before retrying
            if not cricket_data or not cricket_data.get('matches'):
                app_logger.warning("No matches found from API source")
                NEXT_UPDATE_TIMESTAMP["time"] = time.time() + current_interval
                await asyncio.sleep(current_interval)
                continue
            
            # Track match IDs for scorecard cleanup
            current_match_ids = {match.get('match_id'): True for match in cricket_data.get('matches', [])}
                
            # Update scorecards following adaptive checking logic
            if time.time() - last_scorecard_update >= current_interval:  # Use same interval as scores
                app_logger.info("Updating match scorecards...")
                
                scorecard_update_count += 1
                updated_scorecard_count = 0
                
                for match in cricket_data.get('matches', []):
                    match_id = match.get('match_id')
                    match_status = match.get('match_status')
                    
                    # Skip upcoming matches completely - no scorecard needed
                    if match_status == 'upcoming':
                        continue
                    
                    # For completed matches, limit updates to 5 times max
                    if match_status == 'completed':
                        # Check if scorecard already exists
                        existing_scorecard = load_scorecard(match_id)
                        
                        # Get current update count for this completed match
                        update_count = completed_match_update_counts.get(match_id, 0)
                        
                        # Only update if:
                        # 1. No existing scorecard, or
                        # 2. Haven't reached 5 updates yet
                        if not existing_scorecard or update_count < 5:
                            scorecard = fetch_match_scorecard(match_id, logger=app_logger)
                            if scorecard:
                                updated_scorecard_count += 1
                                scorecard_update_times[match_id] = time.time()
                                
                                # Increment update count for this match
                                completed_match_update_counts[match_id] = update_count + 1
                                app_logger.info(f"Updated completed match {match_id} scorecard ({update_count + 1}/5 updates)")
                        else:
                            app_logger.info(f"Skipping completed match {match_id} scorecard update (already updated 5 times)")
                    
                    # For live matches, always update
                    elif match_status == 'live':
                        scorecard = fetch_match_scorecard(match_id, logger=app_logger)
                        if scorecard:
                            updated_scorecard_count += 1
                            scorecard_update_times[match_id] = time.time()
                
                last_scorecard_update = time.time()
                app_logger.info(f"Updated {updated_scorecard_count} scorecards")
                
                # Clean up old scorecard files
                clean_old_scorecards(current_match_ids, logger=app_logger)
            
            # Check if data has changed by creating a simple hash of the match statuses and scores
            current_data_hash = ""
            for match in cricket_data.get('matches', []):
                # Create a string with key match data
                match_hash = f"{match.get('match_id')}:{match.get('status')}:{match.get('score1')}:{match.get('score2')}"
                current_data_hash += match_hash
            
            # Compare with previous data
            if last_data_hash == current_data_hash:
                no_change_count += 1
                app_logger.info(f"No data changes detected. Count: {no_change_count}")
                
                # Adjust interval after 5 consecutive no-change cycles
                if no_change_count % 5 == 0:
                    # Increase interval: 1 min -> 2 min -> 5 min -> 10 min (capped)
                    if current_interval == 60:
                        current_interval = 120  # 2 minutes
                    elif current_interval == 120:
                        current_interval = 300  # 5 minutes
                    elif current_interval < MAX_INTERVAL:
                        current_interval = MAX_INTERVAL  # 10 minutes
                    
                    app_logger.info(f"Adapting update interval to {current_interval} seconds")
            else:
                # Data changed, reset counter and interval
                if no_change_count > 0:
                    app_logger.info("Data changes detected, resetting interval")
                    no_change_count = 0
                    current_interval = MIN_INTERVAL
                
                # Update the hash
                last_data_hash = current_data_hash
            
            # Calculate time spent in processing
            processing_time = time.time() - start_time
            
            # Calculate actual wait time (ensuring we don't have negative wait times)
            actual_wait_seconds = max(1, current_interval - processing_time)
            
            # Check if any matches are starting soon and adjust interval if needed
            now = time.time()
            match_starting_soon = False
            
            # In main.py, update the update_cricket_data function (continued):

            # Look for any matches scheduled to start in the next interval
            for match in cricket_data.get('matches', []):
                if match.get('match_status') == 'upcoming' and match.get('match_time'):
                    time_until_start = match.get('match_time') - now
                    if 0 < time_until_start < current_interval + 60:  # +60s buffer
                        match_starting_soon = True
                        app_logger.info(f"Match starting soon: {match.get('team1')} vs {match.get('team2')}")
                        break
            
            # If a match is about to start, reduce interval
            if match_starting_soon and current_interval > MIN_INTERVAL:
                current_interval = MIN_INTERVAL
                app_logger.info("Match starting soon, reducing update interval")
            
            # Update the timestamp dictionary for the UI
            NEXT_UPDATE_TIMESTAMP["time"] = time.time() + actual_wait_seconds
            
            # Log info about the update
            app_logger.info(f"[{current_time}] Data updated. Next update in {actual_wait_seconds:.1f} seconds.")
            
        except Exception as e:
            app_logger.error(f"[{current_time}] Error updating cricket data: {str(e)}")
            # Don't change the interval on errors
            actual_wait_seconds = current_interval
            NEXT_UPDATE_TIMESTAMP["time"] = time.time() + current_interval
            consecutive_failures += 1
        
        # Wait before updating again
        await asyncio.sleep(actual_wait_seconds)
                
            

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    # Initial data fetch
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        app_logger.info(f"[{current_time}] Initial data fetch...")
        
        # Try CricAPI
        try:
            cricket_data = fetch_live_scores(IGNORED_TOURNAMENTS, logger=app_logger)
            if cricket_data and cricket_data.get('matches'):
                app_logger.info(f"[{current_time}] Initial data loaded from CricAPI")
            else:
                app_logger.warning(f"[{current_time}] CricAPI returned no matches")
        except Exception as e:
            app_logger.error(f"[{current_time}] Error with initial CricAPI fetch: {e}")
    except Exception as e:
        app_logger.error(f"[{current_time}] Error fetching initial cricket data: {e}")
    
    # Start background task
    asyncio.create_task(update_cricket_data())
    
@app.get("/robots.txt")
async def robots_txt():
    return PlainTextResponse(
        content="""User-agent: *
Disallow: /api/
Disallow: /*?
Disallow: /*.json
Disallow: /static/
Allow: /
Allow: /about

# Crawl-delay to slow down bots
Crawl-delay: 10

# Prevent specific bots or aggressive crawlers
User-agent: AhrefsBot
Disallow: /

User-agent: MJ12bot
Disallow: /

User-agent: DotBot
Disallow: /

User-agent: SemrushBot
Disallow: /

User-agent: Yandex
Disallow: /

# Additional protection
Sitemap: https://criclite.com/sitemap.xml""", 
        media_type="text/plain",
        headers={
            "Cache-Control": "public, max-age=86400"
        }
    )

@app.get("/sitemap.xml")
async def sitemap_xml():
    xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://criclite.com/</loc>
    <priority>1.0</priority>
    <changefreq>always</changefreq>
  </url>
  <url>
    <loc>https://criclite.com/about</loc>
    <priority>0.8</priority>
    <changefreq>weekly</changefreq>
  </url>
</urlset>'''
    return Response(
        content=xml_content, 
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )

@app.get("/{match_id}", response_class=HTMLResponse)
async def match_detail(request: Request, match_id: str):
    """Display detailed scorecard for a match"""
    # Get theme from cookie
    theme = request.cookies.get("theme", "light")
    
    # Load cricket data to get match info
    cricket_data = load_cricket_data()
    
    # Find the match
    match_info = None
    for match in cricket_data.get('matches', []):
        if match.get('match_id') == match_id:
            match_info = match
            break
    
    if not match_info:
        return HTMLResponse(content="Match not found", status_code=404)
    
    # Check if this is an upcoming match - redirect to home if so
    match_status = match_info.get('match_status', '')
    if match_status == 'upcoming':
        app_logger.info(f"Redirecting upcoming match {match_id} to home page")
        return RedirectResponse(url="/", status_code=303)
    
    # Load scorecard data
    scorecard_file_data = load_scorecard(match_id)
    # Extract the actual scorecard data from the full file data
    scorecard_data = scorecard_file_data.get('data') if scorecard_file_data else None
    
    # Format match display
    formatted_match = format_match_for_display(match_info)
    
    # Format scorecard as HTML - show second innings first if it's a live match
    show_second_innings_first = match_info.get('match_status') == 'live'
    scorecard_html = format_scorecard_as_html(scorecard_data, match_info, scorecard_file_data, show_second_innings_first) if scorecard_data else None
    
    response = templates.TemplateResponse("match_detail.html", {
        "request": request,
        "theme": theme,
        "match": match_info,
        "formatted_match": formatted_match,
        "scorecard_html": scorecard_html,
        "last_updated": cricket_data.get('last_updated_string', "Unknown"),
        "time_ago": cricket_data.get('time_ago', "Unknown time ago"),
        "match_status": match_status,
        "has_scorecard": bool(scorecard_data)
    })
    
    # Set cache control - use longer cache for completed matches
    if match_status == 'completed':
        response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=7200"  # 1 hour client, 2 hours CDN
    else:
        response.headers["Cache-Control"] = "public, max-age=30, s-maxage=60"  # 30 seconds client, 1 minute CDN
    
    response.headers["Vary"] = "Cookie"
    
    return response

