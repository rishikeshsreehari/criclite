# app/cricket_api_fetcher.py
import requests
import json
import time
import re
from datetime import datetime
from pathlib import Path
import os
from dotenv import load_dotenv
import glob

# Constants
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "data"
DATA_FILE = DATA_FOLDER / "live_data.json"
TOURNAMENT_MAPPING_FILE = DATA_FOLDER / "tournament_mapping.json"
SCORECARD_FOLDER = DATA_FOLDER / "scorecards"
os.makedirs(SCORECARD_FOLDER, exist_ok=True)

# Ensure data directory exists
os.makedirs(DATA_FOLDER, exist_ok=True)

# API configuration functions
def get_api_key():
    """Get fresh API key from environment variables"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not found in environment variables")
    return api_key

def get_api_urls():
    """Get API URLs with fresh API key and timestamp to prevent caching"""
    api_key = get_api_key()
    timestamp = int(time.time())
    current_matches_url = f"https://api.cricapi.com/v1/currentMatches?apikey={api_key}&offset=0&ts={timestamp}"
    cricscore_url = f"https://api.cricapi.com/v1/cricScore?apikey={api_key}&ts={timestamp}"
    return current_matches_url, cricscore_url

# Define priority categories for tournaments
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


def load_tournament_mapping():
    """Load tournament mapping from file"""
    if os.path.exists(TOURNAMENT_MAPPING_FILE):
        try:
            with open(TOURNAMENT_MAPPING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_tournament_mapping(mapping):
    """Save tournament mapping to file"""
    try:
        with open(TOURNAMENT_MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


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


def fetch_current_matches(logger=None):
    """Fetch current matches from CricAPI"""
    try:
        if logger:
            logger.info(f"Fetching current matches from CricAPI")
        
        # Get fresh URL with current API key
        current_matches_url, _ = get_api_urls()
        
        # Log masked URL for debugging
        if logger:
            masked_url = current_matches_url.replace(get_api_key(), "API_KEY_HIDDEN")
            logger.info(f"Requesting URL: {masked_url}")
        
        response = requests.get(current_matches_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Add diagnostic information
            if logger:
                logger.info(f"API response status: {data.get('status')}")
            
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
                    # Log full response for debugging
                    logger.error(f"API error: {data.get('status')}")
                    if 'info' in data:
                        logger.error(f"API info: {data['info']}")
                    logger.error(f"Full response: {data}")
        else:
            if logger:
                logger.error(f"Failed to fetch matches: {response.status_code}")
                try:
                    logger.error(f"Response content: {response.text}")
                except:
                    pass
                
        return None
    except Exception as e:
        if logger:
            logger.error(f"Error fetching matches: {str(e)}")
        return None


def fetch_upcoming_matches(logger=None):
    """Fetch upcoming matches from CricScore API and update tournament mapping"""
    try:
        if logger:
            logger.info(f"Fetching upcoming matches from CricScore API")
        
        # Get fresh URL with current API key
        _, cricscore_url = get_api_urls()
        
        # Log masked URL for debugging
        if logger:
            masked_url = cricscore_url.replace(get_api_key(), "API_KEY_HIDDEN")
            logger.info(f"Requesting URL: {masked_url}")
        
        response = requests.get(cricscore_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Check if the API request was successful
            if data.get('status') == 'success':
                matches = data.get('data', [])
                
                # Log usage info
                if logger and 'info' in data:
                    info = data['info']
                    logger.info(f"API usage: {info.get('hitsUsed', 0)}/{info.get('hitsLimit', 0)} hits today")
                
                # Process upcoming matches (filtering for next 2 days)
                current_time = time.time()
                upcoming_matches = []
                tournament_mapping = load_tournament_mapping()
                
                for match in matches:
                    # Skip if not a fixture (upcoming match)
                    if match.get('ms') != 'fixture':
                        continue
                    
                    # Parse match time
                    match_time = None
                    if match.get('dateTimeGMT'):
                        try:
                            dt = datetime.strptime(match.get('dateTimeGMT'), "%Y-%m-%dT%H:%M:%S")
                            match_time = dt.timestamp()
                        except Exception as e:
                            if logger:
                                logger.error(f"Error parsing time for match {match.get('id')}: {str(e)}")
                            continue
                    
                    # Skip if match time is more than 2 days away
                    if not match_time or match_time > current_time + 172800:  # 48 hours in seconds
                        continue
                    
                    # Check if match is in ignored tournaments
                    series_name = match.get('series', '')
                    if any(ignored in series_name for ignored in IGNORED_TOURNAMENTS):
                        continue
                    
                    # Update tournament mapping
                    match_id = match.get('id', '')
                    
                    if series_name and match_id and series_name not in tournament_mapping:
                        tournament_mapping[series_name] = {
                            'series_id': series_name,
                            'last_updated': time.time(),
                            'priority': get_tournament_priority(series_name)
                        }
                    
                    # Add to upcoming matches
                    upcoming_matches.append(match)
                
                # Save updated tournament mapping
                save_tournament_mapping(tournament_mapping)
                
                if logger:
                    logger.info(f"Found {len(upcoming_matches)} upcoming matches in next 2 days")
                
                return upcoming_matches
            else:
                if logger:
                    logger.error(f"API error: {data.get('status')}")
                    logger.error(f"Full response: {data}")
        else:
            if logger:
                logger.error(f"Failed to fetch upcoming matches: {response.status_code}")
                try:
                    logger.error(f"Response content: {response.text}")
                except:
                    pass
                
        return None
    except Exception as e:
        if logger:
            logger.error(f"Error fetching upcoming matches: {str(e)}")
        return None

def fetch_match_scorecard(match_id, logger=None):
    """Fetch detailed scorecard for a match"""
    try:
        if logger:
            logger.info(f"Fetching scorecard for match {match_id}")
        
        # Get fresh API key
        api_key = get_api_key()
        timestamp = int(time.time())
        
        # Build scorecard API URL
        scorecard_url = f"https://api.cricapi.com/v1/match_scorecard?apikey={api_key}&id={match_id}&ts={timestamp}"
        
        # Log masked URL for debugging
        if logger:
            masked_url = scorecard_url.replace(api_key, "API_KEY_HIDDEN")
            logger.info(f"Requesting scorecard URL: {masked_url}")
        
        response = requests.get(scorecard_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Check if the API request was successful
            if data.get('status') == 'success' and 'data' in data:
                # Save to file
                scorecard_file = SCORECARD_FOLDER / f"{match_id}.json"
                with open(scorecard_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                if logger:
                    logger.info(f"Successfully saved scorecard for match {match_id}")
                
                return data['data']
            else:
                if logger:
                    logger.error(f"API error for scorecard: {data.get('status')}")
                    logger.error(f"Full response: {data}")
        else:
            if logger:
                logger.error(f"Failed to fetch scorecard: {response.status_code}")
                
        return None
    except Exception as e:
        if logger:
            logger.error(f"Error fetching scorecard: {str(e)}")
        return None

def load_scorecard(match_id):
    """Load scorecard from JSON file if it exists"""
    scorecard_file = SCORECARD_FOLDER / f"{match_id}.json"
    if os.path.exists(scorecard_file):
        try:
            with open(scorecard_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('data')
        except Exception:
            pass
    return None

def clean_old_scorecards(current_match_ids, logger=None):
    """Remove scorecard files for matches no longer in the current list"""
    try:
        # Get all scorecard files
        scorecard_files = glob.glob(str(SCORECARD_FOLDER / "*.json"))
        
        # Count before cleaning
        initial_count = len(scorecard_files)
        
        # Check each file
        for file_path in scorecard_files:
            file_name = os.path.basename(file_path)
            match_id = file_name.replace('.json', '')
            
            # If match is not in current matches, delete the file
            if match_id not in current_match_ids:
                os.remove(file_path)
                if logger:
                    logger.info(f"Removed scorecard file for match {match_id}")
        
        # Count after cleaning
        remaining_files = len(glob.glob(str(SCORECARD_FOLDER / "*.json")))
        if logger:
            logger.info(f"Cleaned scorecards: {initial_count - remaining_files} removed, {remaining_files} remaining")
    
    except Exception as e:
        if logger:
            logger.error(f"Error cleaning old scorecards: {str(e)}")

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


def process_criclive_match(match, logger=None):
    """Process match data from CricScore API which can be used for both live and upcoming matches"""
    try:
        match_id = match.get('id', '')
        series = match.get('series', '')
        match_type = match.get('matchType', '').upper()
        date_time_gmt = match.get('dateTimeGMT', '')
        status_text = match.get('status', '')
        match_state = match.get('ms', '')  # 'live', 'result', or 'fixture'
        
        # Get teams
        team1 = match.get('t1', '')
        team2 = match.get('t2', '')
        team1_score = match.get('t1s', '')
        team2_score = match.get('t2s', '')
        
        # Clean team names (remove brackets and content within)
        team1 = re.sub(r'\s*\[.*?\]', '', team1).strip()
        team2 = re.sub(r'\s*\[.*?\]', '', team2).strip()
        
        # Determine match status
        if match_state == 'fixture':
            match_status = 'upcoming'
            is_live = False
        elif match_state == 'live':
            match_status = 'live'
            is_live = True
        else:  # 'result' or other
            match_status = 'completed'
            is_live = False
        
        # Extract match time
        match_time = None
        match_date = ""
        if date_time_gmt:
            try:
                dt = datetime.strptime(date_time_gmt, "%Y-%m-%dT%H:%M:%S")
                match_time = dt.timestamp()
                match_date = dt.strftime("%Y-%m-%d")
            except Exception as e:
                if logger:
                    logger.error(f"Error parsing time for match {match_id}: {str(e)}")
        
        # Create start time info
        start_time_info = ""
        if match_status == 'upcoming' and match_time:
            start_time_info = format_match_time(match_time)
        
        # Get tournament priority
        priority = get_tournament_priority(series, match_type, [team1, team2])
        
        # Create processed data
        processed_data = {
            'match_id': match_id,
            'category': f"{match_type}: {series}" if series else match_type,
            'description': f"Match {match_date}",
            'tournament': series or match_type,
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
            'match_date': match_date,
            'match_type': match_type,
            'match_number': "",
            'venue': "",
            'start_time_info': start_time_info,
            'last_updated': time.time(),
            'last_updated_string': time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
            'source': 'cricscore'
        }
        
        return processed_data
        
    except Exception as e:
        if logger:
            logger.error(f"Error processing CricScore match data: {str(e)}")
        return None


def process_upcoming_match(match, logger=None):
    """Process upcoming match data from CricScore API"""
    try:
        match_id = match.get('id', '')
        series = match.get('series', '')
        match_type = match.get('matchType', '').upper()
        date_time_gmt = match.get('dateTimeGMT', '')
        
        # Get teams
        team1 = match.get('t1', '')
        team2 = match.get('t2', '')
        
        # Clean team names (remove brackets and content within)
        team1 = re.sub(r'\s*\[.*?\]', '', team1).strip()
        team2 = re.sub(r'\s*\[.*?\]', '', team2).strip()
        
        # Extract match time
        match_time = None
        match_date = ""
        if date_time_gmt:
            try:
                dt = datetime.strptime(date_time_gmt, "%Y-%m-%dT%H:%M:%S")
                match_time = dt.timestamp()
                match_date = dt.strftime("%Y-%m-%d")
            except Exception as e:
                if logger:
                    logger.error(f"Error parsing time for upcoming match {match_id}: {str(e)}")
        
        # Create start time info
        start_time_info = ""
        if match_time:
            start_time_info = format_match_time(match_time)
        
        # Get tournament priority
        priority = get_tournament_priority(series, match_type, [team1, team2])
        
        # Create processed data
        processed_data = {
            'match_id': match_id,
            'category': f"{match_type}: {series}" if series else match_type,
            'description': f"Match scheduled for {match_date}",
            'tournament': series or match_type,
            'match_status': 'upcoming',
            'is_live': False,
            'live_state': "",
            'team1': team1,
            'team2': team2,
            'score1': "",
            'score2': "",
            'status': "Match not started",
            'match_info': f"{team1} vs {team2}",
            'link': "",
            'priority': priority,
            'match_time': match_time,
            'local_time': None,
            'timezone': None,
            'match_date': match_date,
            'match_type': match_type,
            'match_number': "",
            'venue': "",
            'start_time_info': start_time_info,
            'last_updated': time.time(),
            'last_updated_string': time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
            'source': 'cricscore'
        }
        
        return processed_data
        
    except Exception as e:
        if logger:
            logger.error(f"Error processing upcoming match data: {str(e)}")
        return None


def merge_upcoming_with_current(current_matches, upcoming_matches, logger=None):
    """Merge upcoming matches from CricScore with current matches from CricAPI"""
    if not upcoming_matches:
        return current_matches
    
    # Create a dictionary of current matches by ID for quick lookup
    current_match_ids = {match.get('match_id'): True for match in current_matches}
    
    added_count = 0
    # Process and add upcoming matches if they don't already exist
    for match in upcoming_matches:
        match_id = match.get('id')
        if match_id and match_id not in current_match_ids:
            processed_match = process_upcoming_match(match, logger)
            if processed_match:
                current_matches.append(processed_match)
                added_count += 1
    
    if logger:
        logger.info(f"Added {added_count} new upcoming matches to the current matches list")
    
    return current_matches

def fetch_live_scores(ignore_list=None, logger=None):
   """Main function to fetch cricket scores from CricAPI with fallbacks"""
   current_time = time.time()
   timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S GMT")
   
   if ignore_list is None:
       ignore_list = IGNORED_TOURNAMENTS
   
   try:
       # Try primary API first
       matches = fetch_current_matches(logger)
       
       if not matches:
           # If primary API fails, try the CricScore API as fallback
           if logger:
               logger.info("Primary API failed, trying CricScore API as fallback")
           
           # Get fresh URL with current API key
           _, cricscore_url = get_api_urls()
           
           cric_score_response = requests.get(cricscore_url, timeout=10)
           if cric_score_response.status_code == 200:
               cric_data = cric_score_response.json()
               if cric_data.get('status') == 'success':
                   if logger:
                       logger.info("Successfully fetched data from CricScore API")
                   
                   # Use all matches from CricScore (includes live, upcoming, and completed)
                   all_matches = cric_data.get('data', [])
                   
                   # Process the matches
                   processed_matches = []
                   for match in all_matches:
                       # Skip ignored tournaments
                       series_name = match.get('series', '')
                       if any(ignored in series_name for ignored in ignore_list):
                           continue
                           
                       processed_match = process_criclive_match(match, logger)
                       if processed_match:
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
                       logger.info(f"Successfully updated cricket data with {len(processed_matches)} matches (from CricScore)")
                   
                   return result
               else:
                   if logger:
                       logger.error(f"CricScore API error: {cric_data.get('status')}")
           else:
               if logger:
                   logger.error(f"Failed to fetch from CricScore: {cric_score_response.status_code}")
           
           # If we get here, both APIs failed
           raise Exception("All API methods failed")
           
       # Continue with normal processing if primary API succeeds
       processed_matches = []
       for match in matches:
           processed_match = process_match(match, logger)
           if processed_match:
               # Only add matches that aren't in the ignore list
               tournament = processed_match.get('tournament', '')
               if not any(ignored in tournament for ignored in ignore_list):
                   processed_matches.append(processed_match)
       
       # Try to fetch upcoming matches
       try:
           upcoming_matches = fetch_upcoming_matches(logger)
           if upcoming_matches:
               processed_matches = merge_upcoming_with_current(processed_matches, upcoming_matches, logger)
       except Exception as e:
           if logger:
               logger.error(f"Error fetching upcoming matches: {str(e)}")
       
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