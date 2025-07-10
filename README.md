# CricLite

> **⚠️ PROJECT CURRENTLY ON HOLD**  
> Due to challenges in finding a reliable and affordable cricket data API provider that aligns with our open-source project goals, CricLite development is currently paused. I'm actively seeking solutions that offer reliable live cricket scores, affordable pricing for open-source projects, comprehensive match coverage, and stable API documentation. If you know of suitable providers or have suggestions, please reach out via GitHub issues or [email](mailto:hello@rishikeshs.com).


CricLite is a lightweight FastAPI application that provides plain text cricket scores and match information. The service fetches live cricket data from the CricData API, processes it, and presents it in a clean, text-based format accessible via both web browsers and terminal.

## Technical Overview

CricLite is built with:

- Python 3.12
- FastAPI for the web framework
- Jinja2 for HTML templating
- CricData API for cricket data
- Async functionality for background updates
- Nginx for web serving

By design, the site is built to be as small and lightweight as possible with everything rendered from the server side. There is no frontend JavaScript, making it extremely fast to load and accessible from virtually any device or browser.

## Installation

### Prerequisites

- Python 3.12 or higher
- Pip package manager
- CricData API key (register at [CricData](https://cricdata.org/))

### Setup

Clone the repository:
```bash
git clone https://github.com/yourusername/criclite.git
cd criclite
```

Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Set up your API key:
```bash
# Rename env.example to .env and add your API key
cp env.example .env
# Then edit the .env file to add your API key from CricData
```

Run the application:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Deployment (AWS EC2)

### Setting up as a Systemd Service

Create a systemd service file:
```bash
sudo nano /etc/systemd/system/criclite.service
```

Add the following configuration:
```
[Unit]
Description=CricLite FastAPI Application
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/criclite
Environment="PATH=/home/ubuntu/criclite/venv/bin"
ExecStart=/home/ubuntu/criclite/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl enable criclite.service
sudo systemctl start criclite.service
```

### Nginx Configuration

Create an Nginx site configuration:
```bash
sudo nano /etc/nginx/sites-available/criclite
```

Add the following configuration:
```
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/criclite /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Usage

### Browser Access

Visit `http://yourdomain.com` or `http://your-server-ip` to view cricket scores in your browser.

### Terminal Access

Get plain text cricket scores in your terminal using curl:
```bash
# Linux/Mac
curl -s https://yourdomain.com/plain.txt

# Windows
curl.exe -s https://yourdomain.com/plain.txt
```

## Project Structure

```
criclite/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application and routes
│   ├── cricket_api_fetcher.py  # Data fetching and processing
│   ├── static/                 # CSS and static files
│   ├── templates/              # Jinja2 templates
│   │   ├── base.html           # Base template
│   │   ├── index.html          # Home page
│   │   ├── head.html           # Header components
│   │   ├── footer.html         # Footer components
│   │   └── about.html          # About page
│   └── data/                   # Data storage directory
│       ├── live_data.json      # Cached match data
│       ├── tournament_mapping.json  # Tournament metadata
│       └── app_log.txt         # Application logs
├── .env                        # Environment variables (API keys)
├── env.example                 # Example environment file
├── requirements.txt            # Project dependencies
└── README.md                   # This file
```

## Data Updates

Currently, scores are updated every minute due to API limitations. In the future, we're planning to update them every 10 seconds for more real-time coverage. The adaptive update system checks for changes in match data and adjusts polling frequency based on activity.

## Troubleshooting

### Common Issues

**502 Bad Gateway**

- Check if the FastAPI service is running: `sudo systemctl status criclite.service`
- Check application logs: `cat /home/ubuntu/criclite/app/data/app_log.txt`
- Ensure all dependencies are installed: `pip install python-dotenv fastapi uvicorn requests`

**No Cricket Data**

- Rename `env.example` to `.env` and add your API key from CricData
- You can get a free API key with a 100 calls/day limit
- Check API usage limits on your CricData account
- Check connectivity to the API server

**Service Won't Start**

- Check the logs: `sudo journalctl -u criclite.service -n 50`
- Ensure Python and all dependencies are installed correctly

## Contributions

We're actively looking for contributors to help improve CricLite! Features in the pipeline include:

- Detailed scorecards
- Live commentary
- Match analysis
- Weather forecasts
- Win predictors

The only constraint is to maintain the HTML-only, server-side rendering approach with pure ASCII (no Unicode) to ensure maximum compatibility and minimal loading times.

## License

GNU AFFERO GENERAL PUBLIC LICENSE
Version 3

## Acknowledgements

- CricData for providing cricket data
- FastAPI for the web framework
- PlainTextSports for inspiration
- Uvicorn for the ASGI server

## Contact

For issues, feature requests, or contributions, please open an issue on GitHub.
