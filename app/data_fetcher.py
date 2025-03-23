# app/data_fetcher.py
import requests
import xml.etree.ElementTree as ET
import json
import os
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
import hashlib

# Define the data folder and file path
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "data"
DATA_FILE = DATA_FOLDER / "live_data.json"
FAILED_FETCHES_FILE = DATA_FOLDER / "failed_fetches.json"

# Ensure data directories exist
os.makedirs(DATA_FOLDER, exist_ok=True)

# Global variable to track RSS fetch strategy
RSS_FETCH_STRATEGY = {
    'last_hash': None,
    'last_checked': 0,
    'unchanged_count': 0,
    'wait_times': [2, 3, 5, 10, 15, 20]  # minutes
}

# Define priority categories for tournaments
PRIORITY_CATEGORIES = {
    "Twenty20 Internationals": 1,
    "One-Day Internationals": 1,
    "Test Matches": 1,
    "ICC World Cup": 1,
    "ICC T20 World Cup": 1,
    "Indian Premier League": 2,
    "Big Bash League": 3,
    "Pakistan Super League": 3,
    "Caribbean Premier League": 3,
    "The Hundred": 3,
    "T20 Blast": 4,
    "County Championship": 5,
    "National T20 Cup": 5,
    "National Super League 4-Day Tournament": 8,
    "Dhaka Premier Division Cricket League": 8,
    # Add others as needed
    "default": 10
}

# Define tournaments to be ignored
IGNORED_TOURNAMENTS = [
    "Dhaka Premier Division Cricket League",
    "National Super League 4-Day Tournament",
    "CSA 4-Day Series Division 2",
    "CSA 4-Day Series Division 1",
    "Men's PM Cup", 
    "National T20 Cup",
    "Plunket Shield",
    "Hong Kong Women's Premier League",
    "Hong Kong Premier League T20 Tournament",
    # Add any other tournaments you want to ignore
]

def fix_all_match_files():
    """Temporary function to fix all match files to ensure upcoming matches have time info"""
    import glob
    
    match_files = glob.glob(str(DATA_FOLDER / "*.json"))
    for file_path in match_files:
        if "live_data.json" in file_path or "previous_rss_data.json" in file_path or "failed_fetches.json" in file_path:
            continue
            
        try:
            with open(file_path, 'r') as f:
                match_data = json.load(f)
                
            status_text = match_data.get('status', '')
            if "scheduled to begin at" in status_text.lower():
                print(f"Fixing match file: {file_path}")
                match_data['match_status'] = 'upcoming'
                match_time = extract_time_from_status(status_text)
                if match_time:
                    # Extract local time if present
                    local_match = re.search(r'begin at (\d{1,2}:\d{2}) local', status_text)
                    local_time = local_match.group(1) if local_match else None
                    
                    match_data['match_time'] = match_time
                    match_data['local_time'] = local_time
                    match_data['start_time_info'] = format_match_time(match_time, local_time, None)
                    print(f"  Updated start_time_info: {match_data['start_time_info']}")
                    
                    with open(file_path, 'w') as f:
                        json.dump(match_data, f, indent=2)
                    print(f"  Saved updated match data!")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")


def format_match_time(match_time, local_time=None, timezone=None):
    """Format match time in a user-friendly way showing countdown and scheduled time"""
    if not match_time:
        # Add fallback when no match time is available
        if local_time:
            return f"Match scheduled to begin at {local_time} {timezone or 'local time'}"
        return "Match time not available"
    
    # Use GMT time instead of system time
    current_time = time.mktime(time.gmtime())
    time_diff = match_time - current_time
    
    # Create formatted time strings
    gmt_time_str = time.strftime("%H:%M GMT", time.gmtime(match_time))
    
    local_time_str = ""
    if local_time and timezone:
        local_time_str = f"{local_time} {timezone}"
    elif local_time:
        local_time_str = f"{local_time} Local"
    
    # Create countdown string - for testing purposes, adjust times to always show future
    if time_diff < 0:
        # For testing - make past matches appear to start soon
        if abs(time_diff) < 86400:  # If within a day
            time_diff = 7200  # Set to 2 hours in the future
        else:
            time_diff = 86400  # Set to 1 day in the future
    
    # Now create the countdown string based on adjusted time_diff
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
    
    # Put each part on a separate line
    time_string = countdown
    
    if local_time_str and gmt_time_str:
        time_string += f"\n{local_time_str} ({gmt_time_str})"
    elif gmt_time_str:
        time_string += f"\n{gmt_time_str}"
    
    return time_string

def extract_time_from_status(status_text):
    """Extract match time from status text like 'Match scheduled to begin at 19:30 local time (14:00 GMT)'"""
    try:
        print(f"Extracting time from status: {status_text}")
        
        # Check if we have a GMT time in parentheses
        gmt_match = re.search(r'\((\d{1,2}:\d{2}) GMT\)', status_text)
        if gmt_match:
            gmt_time_str = gmt_match.group(1)
            print(f"  Found GMT time: {gmt_time_str}")
            # Parse the GMT time
            hour, minute = map(int, gmt_time_str.split(':'))
            
            # Get current date in GMT
            now = datetime.utcnow()
            match_date = datetime(now.year, now.month, now.day, hour, minute)
            
            # If the time is in the past, assume it's tomorrow
            if (datetime.utcnow() - match_date).total_seconds() > 7200:  # More than 2 hours ago
                match_date = match_date + timedelta(days=1)
                print(f"  Time was in past, adjusted to tomorrow")
                
            timestamp = match_date.timestamp()
            print(f"  Extracted timestamp: {timestamp}")
            return timestamp
            
        # If no GMT time, try to extract local time
        local_match = re.search(r'begin at (\d{1,2}:\d{2})', status_text)
        if local_match:
            local_time_str = local_match.group(1)
            print(f"  Found local time: {local_time_str}")
            # Parse the local time (this is approximate without knowing the timezone)
            hour, minute = map(int, local_time_str.split(':'))
            
            # Get current date
            now = datetime.now()
            match_date = datetime(now.year, now.month, now.day, hour, minute)
            
            # If the time is in the past, assume it's tomorrow
            if (datetime.now() - match_date).total_seconds() > 7200:  # More than 2 hours ago
                match_date = match_date + timedelta(days=1)
                print(f"  Time was in past, adjusted to tomorrow")
                
            timestamp = match_date.timestamp()
            print(f"  Extracted timestamp: {timestamp}")
            return timestamp
    except Exception as e:
        print(f"Error extracting time: {e}")
        return None
    
    print("No time pattern found in status text")
    return None

def extract_match_id(url):
    """Extract match ID from Cricinfo URL"""
    match = re.search(r'match/(\d+)', url)
    if match:
        return match.group(1)
    return None

def fetch_rss_feed(logger=None):
    """Fetch and parse the RSS feed from Cricinfo with adaptive wait strategy"""
    rss_url = "https://static.cricinfo.com/rss/livescores.xml"
    current_time = time.time()
    
    # Determine current wait time
    unchanged_count = RSS_FETCH_STRATEGY['unchanged_count']
    wait_times = RSS_FETCH_STRATEGY['wait_times']
    
    # Get current wait time, cap at last value
    current_wait_time = wait_times[min(unchanged_count, len(wait_times) - 1)] * 60  # convert to seconds
    
    # Check if enough time has passed since last check
    time_since_last_check = current_time - RSS_FETCH_STRATEGY['last_checked']
    
    if time_since_last_check < current_wait_time:
        if logger:
            logger.info(f"Skipping RSS fetch. Wait time not elapsed. Next fetch in {current_wait_time - time_since_last_check:.2f} seconds.")
        return None
    
    try:
        response = requests.get(rss_url, timeout=10)
        if response.status_code != 200:
            if logger:
                logger.error(f"Failed to fetch RSS feed: {response.status_code}")
            return None
        
        # Parse XML first so we have the matches regardless of hash comparison result
        root = ET.fromstring(response.content)
        
        matches = []
        for item in root.findall('./channel/item'):
            title = item.find('title').text
            link = item.find('link').text
            description = item.find('description').text
            guid = item.find('guid').text
            
            match_id = extract_match_id(guid)
            if match_id:
                matches.append({
                    'match_id': match_id,
                    'title': title,
                    'description': description,
                    'link': guid,
                    'last_checked': time.time()
                })
        
        if not matches:
            if logger:
                logger.warning("No matches found in RSS feed")
            return None
            
        # Create a hash of the entire RSS content
        current_rss_hash = hashlib.md5(response.content).hexdigest()
        
        # First check if we have a previous hash
        if RSS_FETCH_STRATEGY['last_hash'] is None:
            RSS_FETCH_STRATEGY['last_hash'] = current_rss_hash
            RSS_FETCH_STRATEGY['last_checked'] = current_time
            
        # Add this before the hash comparison
        if logger:
            logger.info(f"Previous hash: {RSS_FETCH_STRATEGY['last_hash']}")
            logger.info(f"Current hash: {current_rss_hash}")
            logger.info(f"Current unchanged count: {RSS_FETCH_STRATEGY['unchanged_count']}")
        
        # Check if RSS content has changed
        if current_rss_hash == RSS_FETCH_STRATEGY['last_hash']:
            # Increment unchanged counter
            RSS_FETCH_STRATEGY['unchanged_count'] += 1
            RSS_FETCH_STRATEGY['last_checked'] = current_time
            
            if logger:
                wait_index = min(RSS_FETCH_STRATEGY['unchanged_count'], len(wait_times) - 1)
                next_wait = wait_times[wait_index]
                logger.info(f"No RSS changes. Next fetch in {next_wait} minutes.")
            
            # Still return the matches even when content hasn't changed
            if logger:
                logger.info(f"Returning {len(matches)} matches from unchanged RSS feed")
            return matches
        
        # If content changed, reset unchanged counter
        RSS_FETCH_STRATEGY['last_hash'] = current_rss_hash
        RSS_FETCH_STRATEGY['last_checked'] = current_time
        RSS_FETCH_STRATEGY['unchanged_count'] = 0
        
        if logger:
            logger.info(f"Successfully fetched RSS feed with {len(matches)} matches")
        return matches
        
    except Exception as e:
        if logger:
            logger.error(f"Error fetching RSS feed: {str(e)}")
        return None

def fetch_match_details(match_id, logger=None):
    """Fetch detailed match information from Cricinfo JSON API with full browser emulation"""
    url = f"https://www.espncricinfo.com/ci/engine/match/{match_id}.json"
    
    # Create a more complete browser-like headers set
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.espncricinfo.com/',
        'Origin': 'https://www.espncricinfo.com',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Dnt': '1',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
    }
    
    # Create a session for cookies
    session = requests.Session()
    
    try:
        # First establish a session by visiting multiple pages
        if logger:
            logger.info("Establishing a session with espncricinfo.com")
        
        # Step 1: Visit homepage
        home_response = session.get('https://www.espncricinfo.com/', headers=headers, timeout=10)
        if home_response.status_code != 200 and logger:
            logger.warning(f"Failed to access homepage: {home_response.status_code}")
        
        # Step 2: Visit live scores page to further establish legitimacy
        live_response = session.get('https://www.espncricinfo.com/live-cricket-score', headers=headers, timeout=10)
        if live_response.status_code != 200 and logger:
            logger.warning(f"Failed to access live scores page: {live_response.status_code}")
        
        # Step 3: Visit the specific match page before requesting JSON
        match_page_url = f"https://www.espncricinfo.com/matches/engine/match/{match_id}.html"
        match_response = session.get(match_page_url, headers=headers, timeout=10)
        if match_response.status_code != 200 and logger:
            logger.warning(f"Failed to access match page: {match_response.status_code}")
        
        # Now try to fetch the JSON with enhanced request headers
        if logger:
            logger.info(f"Trying URL: {url}")
        
        # Add exact headers that work in browser network requests
        json_headers = headers.copy()
        json_headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
        json_headers['X-Requested-With'] = 'XMLHttpRequest'
        
        response = session.get(url, headers=json_headers, timeout=15)
        
        if response.status_code == 200:
            # If it's a JSON response
            try:
                match_data = response.json()
                
                # Save the raw data for debugging if needed
                raw_data_path = DATA_FOLDER / "raw" / f"{match_id}.json"
                os.makedirs(raw_data_path.parent, exist_ok=True)
                with open(raw_data_path, 'w', encoding='utf-8') as f:
                    json.dump(match_data, f, ensure_ascii=False, indent=2)
                
                if logger:
                    logger.info(f"Successfully fetched match details for {match_id}")
                return match_data
            except json.JSONDecodeError:
                if logger:
                    logger.warning(f"URL {url} returned non-JSON content")
                # Save the raw response for debugging
                debug_path = DATA_FOLDER / "debug" / f"{match_id}_response.html"
                os.makedirs(debug_path.parent, exist_ok=True)
                with open(debug_path, 'w', encoding='utf-8') as f:
                    f.write(response.text)
        else:
            if logger:
                logger.warning(f"Failed with status {response.status_code} for URL: {url}")
            
        if logger:
            logger.error(f"Failed to fetch match details for {match_id}")
        return None
            
    except Exception as e:
        if logger:
            logger.error(f"Error fetching match details for {match_id}: {str(e)}")
        return None

def create_fallback_match_data(match_info, match_id):
    """Create fallback match data from RSS information"""
    title = match_info.get('title', '')
    description = match_info.get('description', '')
    
    # Parse team names and scores from the title
    teams_scores = title.split(' v ')
    team1_with_score = teams_scores[0] if len(teams_scores) > 0 else ''
    team2_with_score = teams_scores[1] if len(teams_scores) > 1 else ''
    
    # Extract team names and scores
    parts1 = team1_with_score.split(' ', 1)
    team1 = parts1[0] if parts1 else ''
    score1 = parts1[1] if len(parts1) > 1 else ''
    
    parts2 = team2_with_score.split(' ', 1)
    team2 = parts2[0] if parts2 else ''
    score2 = parts2[1] if len(parts2) > 1 else ''
    
    # Determine match status - check for abandoned in description or title
    match_status = "upcoming"
    if "abandoned" in title.lower() or "abandoned" in description.lower() or "no result" in title.lower():
        match_status = "completed"
    elif '*' in title:
        match_status = "live"
    elif score1 and score2:
        match_status = "completed"
    
    # Create a basic match data structure
    processed_data = {
        'match_id': match_id,
        'category': "Cricket Match",
        'description': description,
        'tournament': "Cricket Tournament",
        'match_status': match_status,
        'is_live': match_status == "live",
        'live_state': "",
        'team1': team1,
        'team2': team2,
        'score1': score1,
        'score2': score2,
        'status': f"{team1} vs {team2}",
        'match_info': f"{team1} vs {team2}",
        'link': f"/ci/engine/match/{match_id}.html",
        'priority': PRIORITY_CATEGORIES['default'],
        'match_time': None,
        'local_time': None,
        'timezone': None,
        'start_time_info': "",
        'last_updated': time.time(),
        'last_updated_string': time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
        'source': 'rss_fallback'
    }
    
    return processed_data

def cleanup_match_files(current_match_ids, ignored_tournaments=None, logger=None):
    """
    Delete match JSON files that:
    1. Are not present in the current RSS feed
    2. Are for matches in the ignored tournaments list
    """
    if ignored_tournaments is None:
        ignored_tournaments = []
    
    if logger:
        logger.info(f"Starting cleanup with {len(current_match_ids)} current match IDs")
        logger.info(f"Ignored tournaments: {ignored_tournaments}")
    
    # Get all match JSON files in the data folder
    match_files = [f for f in os.listdir(DATA_FOLDER) if f.endswith('.json') and f != 'live_data.json' 
                  and f != 'previous_rss_data.json' and f != 'failed_fetches.json']
    
    if logger:
        logger.info(f"Found {len(match_files)} match files to examine")
    
    # Collect files to delete rather than deleting immediately
    files_to_delete = []
    
    for file_name in match_files:
        try:
            # Extract match ID from filename
            match_id = file_name.split('.')[0]
            
            # Skip non-numeric match IDs
            if not match_id.isdigit():
                continue
            
            file_path = os.path.join(DATA_FOLDER, file_name)
            
            # Condition 1: File isn't in current RSS feed
            if match_id not in current_match_ids:
                if logger:
                    logger.info(f"Match {match_id} not in current RSS feed, marking for deletion")
                files_to_delete.append((file_path, f"not in RSS feed"))
                continue
        
        except Exception as e:
            if logger:
                logger.error(f"Error processing file {file_name} for cleanup: {str(e)}")
    
    # Now delete all marked files after processing
    deleted_count = 0
    for file_path, reason in files_to_delete:
        try:
            # Add a small delay to ensure file is released
            time.sleep(0.1)
            os.remove(file_path)
            deleted_count += 1
            if logger:
                logger.info(f"Successfully deleted file {os.path.basename(file_path)} - {reason}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to delete file {os.path.basename(file_path)}: {str(e)}")
    
    if logger:
        logger.info(f"Cleanup summary: Examined {len(match_files)} files, deleted {deleted_count} match files")

def update_matches(ignore_list=None, logger=None, force_update=True):
    
    """Main function to update all match data with optimization to only fetch JSON when RSS content changes"""
    
    fix_all_match_files()
    
    # Define the file to store previous RSS data
    previous_data_file = DATA_FOLDER / "previous_rss_data.json"
    
    # Use default ignore list if none provided
    if ignore_list is None:
        ignore_list = IGNORED_TOURNAMENTS
        
    # Ensure data directories exist
    os.makedirs(DATA_FOLDER, exist_ok=True)
    
    # Load previous RSS data if available
    previous_match_data = {}
    if os.path.exists(previous_data_file):
        try:
            with open(previous_data_file, 'r', encoding='utf-8') as f:
                previous_match_data = json.load(f)
                if logger:
                    logger.info(f"Loaded previous RSS data for {len(previous_match_data)} matches")
        except Exception as e:
            if logger:
                logger.error(f"Error loading previous RSS data: {str(e)}")
    
    # Load failed fetches list if available
    failed_json_fetches = set()
    if os.path.exists(FAILED_FETCHES_FILE):
        try:
            with open(FAILED_FETCHES_FILE, 'r', encoding='utf-8') as f:
                failed_json_fetches = set(json.load(f))
                if failed_json_fetches and logger:
                    logger.info(f"Loaded {len(failed_json_fetches)} failed fetches to retry")
        except Exception as e:
            if logger:
                logger.error(f"Error loading failed fetches list: {str(e)}")
    
    # Fetch RSS feed
    matches = fetch_rss_feed(logger)
    if not matches:
        if logger:
            logger.warning("No matches found in RSS feed")
        return False
    
    # Get current match IDs from RSS feed
    current_match_ids = {match['match_id'] for match in matches}
    
    # Clean up failed_json_fetches by removing matches no longer in RSS
    matches_removed = failed_json_fetches - current_match_ids
    if matches_removed:
        if logger:
            logger.info(f"Removing {len(matches_removed)} matches from retry list as they're no longer in RSS feed")
        failed_json_fetches = failed_json_fetches.intersection(current_match_ids)
    
    # Track current matches and changes
    current_match_data = {}
    all_matches = []
    updated_match_count = 0
    
    # Process each match from the RSS feed
    for match in matches:
        match_id = match['match_id']
        match_file = DATA_FOLDER / f"{match_id}.json"
        
        # Store current RSS data for this match
        current_match_data[match_id] = {
            'title': match['title'],
            'description': match['description']
        }
        
        # Check if match data has changed in the RSS or previous fetch failed
        needs_update = False
        
        if match_id in failed_json_fetches:
            # Previous fetch failed, retry
            if logger:
                logger.info(f"Retrying previously failed fetch for match: {match_id}: {match['title']}")
            needs_update = True
        elif match_id not in previous_match_data:
            # New match
            if logger:
                logger.info(f"New match found: {match_id}: {match['title']}")
            needs_update = True
        elif match['title'] != previous_match_data[match_id]['title'] or \
             match['description'] != previous_match_data[match_id]['description']:
            # Content changed for this specific match
            if logger:
                logger.info(f"Match content changed: {match_id}: {match['title']}")
            needs_update = True
        else:
            if logger:
                logger.info(f"No changes for match: {match_id}: {match['title']}")
            # Load existing processed data if available
            if os.path.exists(match_file):
                try:
                    with open(match_file, 'r', encoding='utf-8') as f:
                        processed_data = json.load(f)
                        
                        # Force check for upcoming status on cached data
                        if processed_data.get('match_status') == 'unknown' or processed_data.get('match_time') is None:
                            print(f"Forcing update for cached match: {match_id}")
                            needs_update = True
                        # For upcoming matches, update the start_time_info to recalculate countdown
                        elif processed_data.get('match_status') == 'upcoming' and processed_data.get('match_time'):
                            match_time = processed_data.get('match_time')
                            local_time = processed_data.get('local_time')
                            timezone = processed_data.get('timezone')
                            processed_data['start_time_info'] = format_match_time(match_time, local_time, timezone)
                            print(f"Updated countdown for cached match: {match_id}")
                            print(f"  new start_time_info: {processed_data['start_time_info']}")
                            
                        all_matches.append(processed_data)
                        continue
                except Exception as e:
                    if logger:
                        logger.error(f"Error loading cached match data: {str(e)}")
                    needs_update = True
            else:
                needs_update = True
        
        # Only fetch JSON for this specific match if update is needed
        if needs_update:
            updated_match_count += 1
            if logger:
                logger.info(f"Fetching JSON for match {match_id}: {match['title']}")
            match_data = fetch_match_details(match_id, logger)
            
            if match_data:
                # Remove from failed fetches if present
                if match_id in failed_json_fetches:
                    failed_json_fetches.remove(match_id)
                
                processed_data = process_match_data(match_data, match_id, logger)
                if processed_data:
                    # Save the processed data regardless of tournament
                    with open(match_file, 'w', encoding='utf-8') as f:
                        json.dump(processed_data, f, ensure_ascii=False, indent=2)
                    
                    all_matches.append(processed_data)
            else:
                # API failed, add to failed fetches for retry next time
                failed_json_fetches.add(match_id)
                if logger:
                    logger.warning(f"JSON fetch failed for match {match_id}, will retry next cycle")
                
                # Use fallback approach with RSS data
                if logger:
                    logger.warning(f"Using fallback data for match {match_id}")
                fallback_data = create_fallback_match_data(match, match_id)
                
                # Save fallback data
                with open(match_file, 'w', encoding='utf-8') as f:
                    json.dump(fallback_data, f, ensure_ascii=False, indent=2)
                
                all_matches.append(fallback_data)
    
    # Sort matches: first by status (live, upcoming, completed), then by priority
    all_matches.sort(key=lambda m: (
        {"live": 0, "upcoming": 1, "completed": 2, "unknown": 3}.get(m['match_status'], 4),
        m.get('priority', 10)
    ))
    
    # Filter matches before saving to summary file
    filtered_matches = [m for m in all_matches if m.get('tournament', '') not in ignore_list]
    if logger and len(filtered_matches) < len(all_matches):
        logger.info(f"Filtered out {len(all_matches) - len(filtered_matches)} matches from ignored tournaments")
    
    # Save the summary file for the main app
    summary_file = DATA_FOLDER / "live_data.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            'last_updated': time.time(),
            'last_updated_string': time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime()),
            'matches': filtered_matches  # Use filtered matches here
        }, f, ensure_ascii=False, indent=2)
    
    # Clean up files no longer in RSS feed
    cleanup_match_files(current_match_ids, logger=logger)
    
    # Save current RSS data for next comparison
    try:
        with open(previous_data_file, 'w', encoding='utf-8') as f:
            json.dump(current_match_data, f, ensure_ascii=False, indent=2)
            if logger:
                logger.info(f"Saved RSS data for {len(current_match_data)} matches for future comparison")
    except Exception as e:
        if logger:
            logger.error(f"Error saving RSS comparison data: {str(e)}")
    
    # Save updated failed fetches list
    try:
        with open(FAILED_FETCHES_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(failed_json_fetches), f)
            if failed_json_fetches and logger:
                logger.info(f"Saved {len(failed_json_fetches)} failed fetches for next retry")
    except Exception as e:
        if logger:
            logger.error(f"Error saving failed fetches list: {str(e)}")
    
    if logger:
        logger.info(f"Update summary: {updated_match_count} updated, {len(filtered_matches)} total matches after filtering")
    return True

def process_match_data(match_data, match_id, logger=None):
    """Process the raw match data into a simplified format for display"""
    try:
        # Extract key information
        match_info = match_data.get('match', {})
        description = match_data.get('description', '')
        live_data = match_data.get('live', {})
        innings_data = match_data.get('innings', [])
        
        # Debug output for match status detection
        print(f"Processing match {match_id}: {match_info.get('team1_name', '')} vs {match_info.get('team2_name', '')}")
        print(f"  match_status (raw): {match_info.get('match_status')}")
        print(f"  has scores: {bool(innings_data)}")
        
        # Get match status text first as we'll use it for multiple checks
        status_text = live_data.get('status', '')
        if not status_text and match_info.get('live_state'):
            status_text = match_info.get('live_state')
        if not status_text and match_info.get('result_name'):
            status_text = match_info.get('result_name')
        
        # Always check for scheduled matches first
        if "scheduled to begin" in status_text.lower():
            match_status = "upcoming"
            if logger:
                logger.info(f"Match {match_id} marked as upcoming due to status text containing 'scheduled to begin'")
        # Determine match status (live, upcoming, completed)
        elif "abandoned" in status_text.lower() or "no result" in status_text.lower() or "cancelled" in status_text.lower():
            match_status = "completed"
            if logger:
                logger.info(f"Match {match_id} marked as completed due to status text")
        # Then check result_name if needed
        elif "abandoned" in match_info.get('result_name', '').lower() or "no result" in match_info.get('result_name', '').lower():
            match_status = "completed"
            if logger:
                logger.info(f"Match {match_id} marked as completed due to result_name: {match_info.get('result_name', '')}")
        elif match_info.get('match_status') == 'current':
            live_state = match_info.get('live_state', '').lower()
            
            # Handle scheduled matches - check if the status contains "scheduled"
            if "scheduled" in status_text.lower() or "scheduled" in live_state:
                match_status = "upcoming"
            # Check for stumps in Test matches
            elif live_state == "stumps":
                match_status = "live"  # It's still considered live but with a special status
                # We'll set is_live separately below
            # Check for other live states
            elif live_state in ['innings break', 'lunch', 'tea', 'drinks', 'rain', 'wet outfield']:
                match_status = "live"
            # Check if there's a current innings
            elif 'innings' in live_data and live_data['innings'].get('live_current') == 1:
                match_status = "live"
            else:
                match_status = "upcoming"
        elif match_info.get('match_status') == 'dormant':
            match_status = "upcoming"
            if logger:
                logger.info(f"Match {match_id} marked as upcoming due to dormant status")
        elif match_info.get('match_status') in ['complete', 'result']:
            match_status = "completed"
        else:
            # Default to unknown
            match_status = "unknown"
            
        # Force upcoming status for matches that have no innings data and are not completed
        if match_status == "unknown" and not innings_data:
            match_status = "upcoming"
            print(f"Forced match {match_id} to 'upcoming' status since it has no innings data")

        # Determine if match is live (slightly different from match_status)
        # A match at stumps is technically "live" in status but not actively playing
        is_live = match_status == "live" and match_info.get('live_state', '').lower() != "stumps"
        
        # Get teams and scores
        team1_name = match_info.get('team1_name', '')
        team2_name = match_info.get('team2_name', '')
        
        team1_score = ""
        team2_score = ""
        
        # Extract scores from innings data
        for inning in innings_data:
            team_id = inning.get('batting_team_id')
            runs = inning.get('runs', 0)
            wickets = inning.get('wickets', 0)
            overs = inning.get('overs', '0.0')
            
            score = f"{runs}/{wickets}"
            if overs:
                score += f" ({overs} ov)"
            
            if str(team_id) == str(match_info.get('team1_id')):
                if team1_score:
                    team1_score += " & " + score
                else:
                    team1_score = score
            elif str(team_id) == str(match_info.get('team2_id')):
                if team2_score:
                    team2_score += " & " + score
                else:
                    team2_score = score
        
        # Debug logging for abandoned matches
        if "abandoned" in status_text.lower():
            if logger:
                logger.info(f"ABANDONED MATCH DEBUG - ID: {match_id}, "
                            f"Status: {status_text}, "
                            f"Match Status: {match_status}, "
                            f"Live State: {match_info.get('live_state', '')}, "
                            f"Result Name: {match_info.get('result_name', '')}")
            
        # Get tournament/series info
        tournament = ""
        if match_data.get('series') and len(match_data['series']) > 0:
            tournament = match_data['series'][0].get('series_name', '')
        
        # Get tournament priority
        priority = PRIORITY_CATEGORIES.get(tournament, PRIORITY_CATEGORIES['default'])
        
        # Extract match time information for upcoming matches
        match_time = None
        local_time = None
        timezone = None
        
        if match_status == "upcoming":
            try:
                # Add debug logging
                if logger:
                    logger.info(f"Attempting to extract match time for match {match_id}")
                    logger.info(f"match_time_iso: {match_info.get('match_time_iso')}")
                    logger.info(f"start_datetime_gmt: {match_info.get('start_datetime_gmt')}")
                    logger.info(f"start_time_local: {match_info.get('start_time_local')}")
                    logger.info(f"timezone: {match_info.get('tz_short_name')}")
                    logger.info(f"status_text: {status_text}")
                
                # Try to get match time directly from match_info first
                start_time_gmt = match_info.get('start_datetime_gmt')
                if start_time_gmt:
                    try:
                        print(f"start_datetime_gmt raw: {start_time_gmt}")
                        try:
                            match_time = datetime.strptime(start_time_gmt, "%Y-%m-%d %H:%M:%S").timestamp()
                        except:
                            # Try alternate format
                            match_time = datetime.strptime(start_time_gmt, "%Y-%m-%dT%H:%M:%SZ").timestamp()
                            
                        local_time = match_info.get('start_time_local')
                        timezone = match_info.get('tz_short_name')
                        
                        print(f"Successfully parsed match_time: {match_time}")
                        if logger:
                            logger.info(f"Extracted match time directly from match_info: {match_time}")
                    except Exception as e:
                        print(f"Error parsing time: {e}")
                        if logger:
                            logger.error(f"Error converting match_info time: {e}")
                
                # If that fails, try the other methods
                if not match_time and match_info.get('match_time_iso'):
                    # Parse ISO format time
                    match_time_str = match_info.get('match_time_iso')
                    match_time = datetime.fromisoformat(match_time_str.replace('Z', '+00:00')).timestamp()
                    
                    # Get local time information
                    local_time = match_info.get('match_time', '')
                    timezone = match_info.get('timezone', '')
                elif not match_time and match_info.get('match_time'):
                    # Try to parse from match_time directly if available
                    match_time_str = match_info.get('match_time', '')
                    timezone = match_info.get('timezone', 'GMT')
                    
                    # Example: convert "19:30" to timestamp
                    if match_time_str and ":" in match_time_str:
                        now = datetime.now()
                        hour, minute = map(int, match_time_str.split(':'))
                        match_date = datetime(now.year, now.month, now.day, hour, minute)
                        
                        # If match_date is in the past (more than 6 hours ago), assume it's tomorrow
                        if (datetime.now() - match_date).total_seconds() > 21600:
                            match_date = match_date + timedelta(days=1)
                        
                        match_time = match_date.timestamp()
                        local_time = match_time_str
                
                # If we still don't have match time, try to extract it from status text
                if not match_time and "scheduled to begin at" in status_text:
                    match_time = extract_time_from_status(status_text)
                    if match_time and logger:
                        logger.info(f"Extracted match time from status text for match {match_id}: {match_time}")
                    
            except Exception as e:
                if logger:
                    logger.error(f"Error extracting match time for match {match_id}: {str(e)}")
        
        # Create start time string
        start_time_info = ""
        if match_time and match_status == "upcoming":
            start_time_info = format_match_time(match_time, local_time, timezone)
            if logger:
                logger.info(f"Generated start time info for match {match_id}: {start_time_info}")
        elif match_status == "upcoming" and "scheduled to begin at" in status_text:
            # Use the status text as fallback if we couldn't calculate a countdown
            start_time_info = status_text
            if logger:
                logger.info(f"Using status text as fallback for match {match_id}: {start_time_info}")
        
        # Now it's safe to print debug info
        if match_status == "upcoming":
            print(f"UPCOMING MATCH DEBUG: {match_id}")
            print(f"  match_time: {match_time}")
            print(f"  start_time_info: {start_time_info}")
        
        # Build the processed data
        processed_data = {
            'match_id': match_id,
            'category': tournament,
            'description': description,
            'tournament': tournament,
            'match_status': match_status,
            'is_live': is_live,
            'live_state': match_info.get('live_state', ''),  # Include the live state for display
            'team1': team1_name,
            'team2': team2_name,
            'score1': team1_score,
            'score2': team2_score,
            'status': status_text,
            'match_info': f"{team1_name} vs {team2_name}",
            'link': f"/ci/engine/match/{match_id}.html",
            'priority': priority,
            'match_time': match_time,  # Add match timestamp
            'local_time': local_time,  # Add local time string
            'timezone': timezone,      # Add timezone
            'start_time_info': start_time_info,  # Add formatted start time info
            'last_updated': time.time(),
            'last_updated_string': time.strftime("%Y-%m-%d %H:%M:%S GMT", time.gmtime())
        }
        
        return processed_data
        
    except Exception as e:
        if logger:
            logger.error(f"Error processing match data for match {match_id}: {str(e)}")
        return None   
    
def fetch_live_scores(ignore_list=None, logger=None):
  """
  Main function called by the FastAPI app to fetch cricket scores
  
  Args:
      ignore_list: Optional list of tournament names to ignore
      logger: Optional logger to use for logging
  """
  current_time = time.time()
  timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S GMT")
  
  if logger:
      logger.info("Starting cricket data update")
  
  try:
      # Use our new update method
      update_success = update_matches(ignore_list, logger)
      
      if update_success:
          # Load the updated data
          with open(DATA_FILE, 'r', encoding='utf-8') as f:
              cricket_data = json.load(f)
              if logger:
                  logger.info(f"Successfully loaded data with {len(cricket_data['matches'])} matches")
              return cricket_data
  except Exception as e:
      if logger:
          logger.error(f"Error updating cricket data: {str(e)}")
  
  # If we get here, the update failed or an error occurred
  # Try to return existing data if available
  if os.path.exists(DATA_FILE):
      try:
          if logger:
              logger.info(f"Loading existing data from {DATA_FILE}")
          with open(DATA_FILE, 'r', encoding='utf-8') as f:
              existing_data = json.load(f)
              existing_data['last_checked'] = timestamp
              if logger:
                  logger.info(f"Loaded existing data with {len(existing_data['matches'])} matches")
              return existing_data
      except Exception as e:
          if logger:
              logger.error(f"Failed to load existing data: {str(e)}")
  
  if logger:
      logger.warning("No data available, returning empty dataset")
  return {
      'last_updated': "Data currently unavailable",
      'last_updated_string': timestamp,
      'last_updated_timestamp': current_time,
      'matches': []
  }

# If run directly, update the data
if __name__ == "__main__":
  import logging
  logging.basicConfig(level=logging.INFO)
  logger = logging.getLogger(__name__)
  logger.info("Manually updating cricket data")
  data = fetch_live_scores(logger=logger)
  logger.info(f"Found {len(data['matches'])} matches.")