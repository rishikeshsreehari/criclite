# app/data_fetcher.py
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime

def fetch_live_scores():
    """Fetch live cricket scores from Cricinfo live matches page"""
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
            
            # Find all matches in this category
            match_block = section.find_next('section', class_='matches-day-block')
            matches = match_block.find_all('section', class_='default-match-block')
            
            for match in matches:
                # Check if match is live
                is_live = match.find('span', class_='live-icon') is not None
                
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
                
                # Get match link
                link = ""
                match_no = match.find('span', class_='match-no')
                if match_no and match_no.find('a'):
                    link = match_no.find('a')['href']
                
                match_data = {
                    'category': category,
                    'is_live': is_live,
                    'match_info': match_info,
                    'team1': team1,
                    'score1': score1,
                    'team2': team2,
                    'score2': score2,
                    'status': status,
                    'link': link
                }
                
                all_matches.append(match_data)
        
        return {
            'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'last_updated_timestamp': current_time,
            'matches': all_matches
        }
        
    except requests.RequestException as e:
        print(f"Error fetching cricket data: {e}")
        return {
            'last_updated': "Data currently unavailable",
            'last_updated_timestamp': current_time,
            'matches': []
        }