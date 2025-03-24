# app/cricket_api_fetcher.py
import requests
import json
import time
from datetime import datetime
from pathlib import Path
import os
import logging

# Constants
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "data"
DATA_FILE = DATA_FOLDER / "live_data.json"

# API configuration
API_KEY = "fa463534-a8d3-491f-83b7-ee36bc0c9602"
CURRENT_MATCHES_URL = f"https://api.cricapi.com/v1/currentMatches?apikey={API_KEY}&offset=0"

# Define priority categories for tournaments (similar to your existing structure)
PRIORITY_CATEGORIES = {
    "ICC World Cup": 1,
    "ICC T20 World Cup": 1,
    "World Test Championship": 1,
    "Indian Premier League": 2,
    "IPL": 2,
    "Big Bash League": 3,
    "Pakistan Super League": 3,
    "Caribbean Premier League": 3,
    "The Hundred": 3,
    "International T20": 2,
    "International ODI": 2,
    "Test Match": 2,
    "Women's": 3,
    "default": 10
}

# Top international teams
TOP_TEAMS = [
    'india', 'australia', 'england', 'south africa', 'new zealand', 
    'pakistan', 'bangladesh', 'sri lanka', 'west indies', 'afghanistan'
]


# Tournaments to ignore
# Expanded ignore list
IGNORED_TOURNAMENTS = [
    "Dhaka Premier Division Cricket League",
    "National Super League 4-Day Tournament",
    "CSA 4-Day Series Division 2",
    "CSA 4-Day Series Division 1",
    "Men's PM Cup", 
    "National T20 Cup",
    "Plunket Shield",
    "Sheffield Shield",
    "County Championship Division 1",
    "County Championship Division 2",
    "Bangladesh Cricket League",
    "Ranji Trophy Plate",
    # Add more tournaments to ignore here
]


def get_tournament_priority(match_name, match_type=None, teams=None):
    """Get priority level for a match based on tournament, match type and teams"""
    match_name_lower = match_name.lower() if match_name else ""
    
    # First check explicit tournament priorities
    for tournament, priority in PRIORITY_CATEGORIES.items():
        if tournament.lower() in match_name_lower:
            return priority
    
    # If match_type and teams are provided, use them for additional priority rules
    if match_type and teams:
        # Check for international matches between top teams
        has_top_team = any(team.lower() in ' '.join(TOP_TEAMS) for team in teams)
        
        # Prioritize by match type for international matches
        if has_top_team:
            if match_type == 'T20':
                return PRIORITY_CATEGORIES.get("International T20", 2)
            elif match_type == 'ODI':
                return PRIORITY_CATEGORIES.get("International ODI", 2)
            elif match_type == 'TEST':
                return PRIORITY_CATEGORIES.get("Test Match", 2)
        
        # Check for women's matches
        if 'women' in match_name_lower:
            return PRIORITY_CATEGORIES.get("Women's", 3)
    
    # Default priority
    return PRIORITY_CATEGORIES.get('default', 10)

def fetch_current_matches(logger=None):
    """Fetch current matches from CricAPI"""
    try:
        if logger:
            logger.info(f"Fetching current matches from CricAPI")
        
        response = requests.get(CURRENT_MATCHES_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Check if the API request was successful
            if data.get('status') == 'success':
                matches = data.get('data', [])
                
                # Log usage info
                if logger and 'info' in data:
                    info = data['info']
                    logger.info(f"API usage: {info.get('hitsUsed', 0)}/{info.get('hitsLimit', 0)} hits today, {info.get('totalRows', 0)} matches found")
                
                return matches
            else:
                if logger:
                    logger.error(f"API error: {data.get('status')}")
        else:
            if logger:
                logger.error(f"Failed to fetch matches: {response.status_code}")
                
        return None
    except Exception as e:
        if logger:
            logger.error(f"Error fetching matches: {str(e)}")
        return None

def determine_match_status(match):
    """Determine match status (live, completed, upcoming) from CricAPI data"""
    status_text = match.get('status', '').lower()
    
    # Check if match has started
    if not match.get('matchStarted', False):
        return 'upcoming'
    
    # Check if match has ended
    if match.get('matchEnded', False):
        return 'completed'
    
    # Check for keywords indicating completed matches
    if any(word in status_text for word in ['won by', 'tied', 'abandoned', 'no result']):
        return 'completed'
    
    # For test matches with stumps or other breaks
    if 'stumps' in status_text or 'lunch' in status_text or 'tea' in status_text:
        return 'live'  # Still considered live, though not actively playing
        
    # If match has started but not ended, it's live
    return 'live'

def is_actively_live(match):
    """Determine if match is actively live (not at stumps/tea/lunch)"""
    status_text = match.get('status', '').lower()
    
    # Match must be in 'live' state but not in a break
    if determine_match_status(match) == 'live':
        return not any(word in status_text for word in ['stumps', 'lunch', 'tea', 'drinks', 'rain'])
    
    return False

def format_score(score_entry):
    """Format score data from CricAPI"""
    if not score_entry:
        return ""
        
    runs = score_entry.get('r', 0)
    wickets = score_entry.get('w', 0)
    overs = score_entry.get('o', 0)
    
    score = f"{runs}/{wickets}"
    if overs:
        score += f" ({overs} ov)"
        
    return score

def parse_match_time(date_time_gmt):
    """Convert GMT time string to timestamp"""
    try:
        dt = datetime.strptime(date_time_gmt, "%Y-%m-%dT%H:%M:%S")
        return dt.timestamp()
    except Exception:
        return None

def format_match_time(timestamp):
    """Format match time to display countdown"""
    if not timestamp:
        return "Match time not available"
        
    current_time = time.time()
    time_diff = timestamp - current_time
    
    # Format GMT time
    gmt_time_str = time.strftime("%H:%M GMT", time.gmtime(timestamp))
    
    # For testing - make past matches appear to start soon
    if time_diff < 0:
        if abs(time_diff) < 86400:  # If within a day
            time_diff = 7200  # Set to 2 hours in the future
        else:
            time_diff = 86400  # Set to 1 day in the future
    
    # Create countdown string
    if time_diff < 60:
        countdown = "Starting in less than a minute"
    elif time_diff < 3600:
        minutes = int(time_diff // 60)
        countdown = f"Starts in {minutes} minute{'s' if minutes > 1 else ''}"
    elif time_diff < 86400:
        hours = int(time_diff // 3600)
        countdown = f"Starts in {hours} hour{'s' if hours > 1 else ''}"
    elif time_diff < 172800:
        countdown = "Starts tomorrow"
    else:
        days = int(time_diff // 86400)
        countdown = f"Starts in {days} day{'s' if days > 1 else ''}"
    
    # Combine countdown with time
    return f"{countdown}\n{gmt_time_str}"


def process_match(match, logger=None):
    """Process match data from CricAPI into application format"""
    try:
        match_id = match.get('id', '')
        match_name = match.get('name', '')
        status_text = match.get('status', '')
        venue = match.get('venue', '')
        date = match.get('date', '')
        match_type = match.get('matchType', '').upper()
        date_time_gmt = match.get('dateTimeGMT', '')
        
        # Determine match status (live, completed, upcoming)
        match_status = determine_match_status(match)
        is_live = is_actively_live(match)
        
        # Extract series/tournament name and match number
        tournament = ""
        match_number = ""
        if "," in match_name:
            parts = match_name.split(",")
            if len(parts) > 1:
                tournament = parts[1].strip()
                # Try to extract match number
                if "Match" in tournament:
                    match_parts = tournament.split("Match")
                    if len(match_parts) > 1:
                        match_number = "Match" + match_parts[1]
                        tournament = match_parts[0].strip()
        
        # Get teams
        teams = match.get('teams', [])
        team1 = teams[0] if len(teams) > 0 else ''
        team2 = teams[1] if len(teams) > 1 else ''
        
        # Get scores
        score_entries = match.get('score', [])
        team1_score = ""
        team2_score = ""
        
        # Match innings to teams
        for score_entry in score_entries:
            inning_name = score_entry.get('inning', '').lower()
            formatted_score = format_score(score_entry)
            
            if team1.lower() in inning_name:
                if team1_score:
                    team1_score += " & " + formatted_score
                else:
                    team1_score = formatted_score
            elif team2.lower() in inning_name:
                if team2_score:
                    team2_score += " & " + formatted_score
                else:
                    team2_score = formatted_score
        
        # Extract match time
        match_time = parse_match_time(date_time_gmt) if date_time_gmt else None
        
        # Create start time info for upcoming matches
        start_time_info = ""
        if match_status == 'upcoming' and match_time:
            start_time_info = format_match_time(match_time)
        elif match_status == 'upcoming':
            # Fallback if time parsing failed
            start_time_info = f"Match scheduled for {date}"
        
        # Get tournament priority
        priority = get_tournament_priority(match_name, match_type, teams)
        
        # Build description (venue and date)
        description = f"Match at {venue}, {date}"
        
        # Create processed data
        processed_data = {
            'match_id': match_id,
            'category': f"{match_type}: {tournament}" if tournament else match_type,
            'description': description,
            'tournament': tournament or match_type,
            'match_status': match_status,
            'is_live': is_live,
            'live_state': "In Progress" if is_live else "",
            'team1': team1,
            'team2': team2,
            'score1': team1_score,
            'score2': team2_score,
            'status': status_text,
            'match_info': f"{team1} vs {team2}",
            'link': "",
            'priority': priority,
            'match_time': match_time,
            'local_time': None,
            'timezone': None,
            'match_date': date,
            'match_type': match_type,
            'match_number': match_number,
            'venue': venue,
            'start_time_info': start_time_info,
            'last_updated': time.time(),
            'last_updated_string': time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
            'source': 'cricapi'
        }
        
        return processed_data
        
    except Exception as e:
        if logger:
            logger.error(f"Error processing match data: {str(e)}")
        return None


def fetch_live_scores(ignore_list=None, logger=None):
    """Main function to fetch cricket scores from CricAPI"""
    current_time = time.time()
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S GMT")
    
    if ignore_list is None:
        ignore_list = IGNORED_TOURNAMENTS
    
    try:
        # Fetch current matches
        matches = fetch_current_matches(logger)
        
        if not matches:
            raise Exception("Failed to fetch matches")
        
        # Process matches
        processed_matches = []
        for match in matches:
            processed_match = process_match(match, logger)
            if processed_match:
                # Only add matches that aren't in the ignore list
                tournament = processed_match.get('tournament', '')
                if not any(ignored in tournament for ignored in ignore_list):
                    processed_matches.append(processed_match)
        
        # Sort matches by status and priority
        processed_matches.sort(key=lambda m: (
            {"live": 0, "upcoming": 1, "completed": 2}.get(m['match_status'], 3),
            m.get('priority', 10)
        ))
        
        # Create the result data
        result = {
            'last_updated': current_time,
            'last_updated_string': timestamp,
            'matches': processed_matches
        }
        
        # Save to file
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        if logger:
            logger.info(f"Successfully updated cricket data with {len(processed_matches)} matches")
        
        return result
        
    except Exception as e:
        if logger:
            logger.error(f"Error updating cricket data: {str(e)}")
        
        # Try to return existing data if available
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_data['last_checked'] = timestamp
                    if logger:
                        logger.info(f"Loaded existing data with {len(existing_data['matches'])} matches")
                    return existing_data
            except Exception as load_error:
                if logger:
                    logger.error(f"Failed to load existing data: {str(load_error)}")
        
        # Return empty data if nothing else works
        return {
            'last_updated': current_time,
            'last_updated_string': timestamp,
            'matches': []
        }

# If run directly, update the data
# Corrected version:
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("Manually updating cricket data")
    data = fetch_live_scores(logger=logger)
    logger.info(f"Found {len(data['matches'])} matches.")