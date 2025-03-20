# app/data_fetcher.py
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import json
import os
import re
from pathlib import Path

# Define the data folder and file path
BASE_DIR = Path(__file__).resolve().parent
DATA_FOLDER = BASE_DIR / "data"
DATA_FILE = DATA_FOLDER / "live_data.json"

# Define priority categories
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
    "National T20 Cup": 5,
    "Durham tour of Zimbabwe": 6,
    "Men's PM Cup": 7,
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
    # Add any other tournaments you want to ignore
]

def determine_match_status(status_text, is_live_icon_present):
    """
    Determine the actual status of a match based on its status text
    and whether it has a live icon
    """
    status_text = status_text.lower() if status_text else ""
    
    # Completed matches
    if "won by" in status_text:
        return "completed"
    # Scheduled matches
    elif "scheduled" in status_text or "begin" in status_text:
        return "scheduled"
    # Live matches - either has live icon or indicates in-progress status
    elif is_live_icon_present or any(term in status_text for term in ["lead by", "trail by", "require", "at stumps", "in progress", "lunch", "tea", "drinks"]):
        return "live"
    else:
        return "unknown"

def fetch_live_scores(ignore_list=None):
    """
    Fetch live cricket scores from Cricinfo live matches page and store in JSON
    
    Args:
        ignore_list: Optional list of tournament names to ignore
    """
    # Use default ignore list if none provided
    if ignore_list is None:
        ignore_list = IGNORED_TOURNAMENTS
        
    url = "https://www.espncricinfo.com/ci/engine/match/index/live.html"
    
    # Set headers to mimic a browser request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    }
    
    current_time = time.time()
    # Use UTC time with a compatible approach
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S GMT")
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse HTML content
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find match sections
        match_sections = soup.find_all('div', class_='match-section-head')
        
        # Create a list to store all matches
        all_matches = []
        
        for section in match_sections:
            category = section.find('h2').text.strip()
            
            # Skip ignored tournaments
            if category in ignore_list:
                print(f"Skipping ignored tournament: {category}")
                continue
            
            # Find all matches in this category
            match_block = section.find_next('section', class_='matches-day-block')
            matches = match_block.find_all('section', class_='default-match-block')
            
            for match in matches:
                # Check if match has a live icon
                has_live_icon = match.find('span', class_='live-icon') is not None
                
                # Get match info
                match_info = match.find('div', class_='match-info').text.strip()
                
                # Get teams and scores
                innings1 = match.find('div', class_='innings-info-1')
                innings2 = match.find('div', class_='innings-info-2')
                
                team1 = ""
                score1 = ""
                team2 = ""
                score2 = ""
                
                if innings1:
                    innings1_text = innings1.text.strip()
                    if innings1_text:
                        parts = innings1_text.split(None, 1)
                        team1 = parts[0].strip()
                        if len(parts) > 1:
                            score1 = parts[1].strip()
                
                if innings2:
                    innings2_text = innings2.text.strip()
                    if innings2_text:
                        parts = innings2_text.split(None, 1)
                        team2 = parts[0].strip()
                        if len(parts) > 1:
                            score2 = parts[1].strip()
                
                # Get match status
                status_div = match.find('div', class_='match-status')
                status = status_div.text.strip() if status_div else ""
                
                # Determine the actual match status
                match_status = determine_match_status(status, has_live_icon)
                
                # Get match link
                link = ""
                match_no = match.find('span', class_='match-no')
                if match_no and match_no.find('a'):
                    link = match_no.find('a')['href']
                
                # Store the tournament priority directly in the match data
                tournament_priority = PRIORITY_CATEGORIES.get(category, PRIORITY_CATEGORIES['default'])
                
                match_data = {
                    'category': category,
                    'is_live': match_status == "live",
                    'match_status': match_status,  # Store the detailed status
                    'tournament_priority': tournament_priority,  # Store priority directly
                    'match_info': match_info,
                    'team1': team1,
                    'score1': score1,
                    'team2': team2,
                    'score2': score2,
                    'status': status,
                    'link': link
                }
                
                all_matches.append(match_data)
        
        # Group matches by category
        tournaments = {}
        for match in all_matches:
            category = match['category']
            if category not in tournaments:
                tournaments[category] = {
                    'name': category,
                    'priority': PRIORITY_CATEGORIES.get(category, PRIORITY_CATEGORIES['default']),
                    'matches': []
                }
            tournaments[category]['matches'].append(match)

        # Sort tournaments by priority only (not by status)
        sorted_tournaments = sorted(tournaments.values(), 
                                  key=lambda t: t['priority'])

        # For each tournament, sort its matches by status
        for tournament in sorted_tournaments:
            tournament['matches'] = sorted(tournament['matches'], 
                                         key=lambda m: {
                                             "live": 0,
                                             "completed": 20,
                                             "scheduled": 30,
                                             "unknown": 40
                                         }.get(m['match_status'], 100))

        # Flatten matches back into a list in correct order
        final_matches = []
        for tournament in sorted_tournaments:
            for match in tournament['matches']:
                final_matches.append(match)
        
        # Print tournament order for debugging
        print("Tournament order:")
        for t in sorted_tournaments:
            print(f"- {t['name']} (Priority: {t['priority']})")
        
        # Create the data structure
        cricket_data = {
            'last_updated': timestamp,
            'last_updated_timestamp': current_time,
            'matches': final_matches,
            'tournaments': [t['name'] for t in sorted_tournaments]  # Store ordered tournament names
        }
        
        # Ensure data directory exists
        os.makedirs(DATA_FOLDER, exist_ok=True)
        
        # Save to JSON file
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(cricket_data, f, ensure_ascii=False, indent=2)
            
        return cricket_data
        
    except requests.RequestException as e:
        print(f"Error fetching cricket data: {e}")
        
        # If we have existing data, load it instead of returning empty
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    existing_data['last_checked'] = timestamp
                    return existing_data
            except:
                pass
        
        return {
            'last_updated': "Data currently unavailable",
            'last_updated_timestamp': current_time,
            'matches': []
        }

# If run directly, update the data
if __name__ == "__main__":
    print(f"Updating cricket data at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    data = fetch_live_scores()
    print(f"Found {len(data['matches'])} matches.")