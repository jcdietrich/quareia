#!/usr/bin/env python3
import sys
import os
import shutil
import datetime
import math
import re
import requests
from google import genai
from PIL import Image
import build
import ephem

# Default Coordinates (Kitchener, ON, Canada)
DEFAULT_LAT = '43.4254'
DEFAULT_LON = '-80.5112'
DEFAULT_ELEVATION = 300 # Approx for Kitchener
DEFAULT_LOCATION_NAME = "Kitchener, ON, Canada"

def get_coordinates_from_name(place_name):
    """
    Geocodes a place name to (lat, lon) using Open-Meteo.
    Returns (lat, lon) as strings, or None if not found.
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    # Simple heuristic: take first part of comma-separated string for search
    search_name = place_name.split(',')[0].strip()
    
    params = {
        "name": search_name,
        "count": 1,
        "language": "en",
        "format": "json"
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if "results" in data and len(data["results"]) > 0:
            result = data["results"][0]
            return str(result["latitude"]), str(result["longitude"])
    except Exception as e:
        print(f"Error geocoding '{place_name}': {e}")
    
    return None

def get_weather_condition(code):
    # WMO Weather interpretation codes (WW)
    codes = {
        0: "Clear sky",
        1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Drizzle: Light", 53: "Drizzle: Moderate", 55: "Drizzle: Dense intensity",
        56: "Freezing Drizzle: Light", 57: "Freezing Drizzle: Dense intensity",
        61: "Rain: Slight", 63: "Rain: Moderate", 65: "Rain: Heavy intensity",
        66: "Freezing Rain: Light", 67: "Freezing Rain: Heavy intensity",
        71: "Snow fall: Slight", 73: "Snow fall: Moderate", 75: "Snow fall: Heavy intensity",
        77: "Snow grains",
        80: "Rain showers: Slight", 81: "Rain showers: Moderate", 82: "Rain showers: Violent",
        85: "Snow showers slight", 86: "Snow showers heavy",
        95: "Thunderstorm: Slight or moderate",
        96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
    }
    return codes.get(code, "Unknown")

def get_weather_data(dt, lat=DEFAULT_LAT, lon=DEFAULT_LON):
    # dt should be a datetime object
    date_str = dt.strftime("%Y-%m-%d")
    
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,weather_code",
        "timezone": "auto", # Use auto to get local time based on coords ideally, or match logic
        "start_date": date_str,
        "end_date": date_str
    }
    
    # Note: timezone 'auto' tries to resolve timezone from coordinates. 
    # Since we are passing diverse coords, this is safer than hardcoding America/New_York.
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if "hourly" not in data:
            return "N/A", "N/A"
            
        # The hourly data array corresponds to local time 00:00 to 23:00 if timezone is set correctly.
        # However, we have 'dt' which is presumably in the *local time of the user/journal*.
        # Let's assume the API returns data in local time of the requested location.
        
        target_hour = dt.hour
        
        idx = target_hour
        if 0 <= idx < len(data['hourly']['time']):
            temp = data['hourly']['temperature_2m'][idx]
            code = data['hourly']['weather_code'][idx]
            
            condition = get_weather_condition(code)
            return f"{temp}°C", condition
        
    except Exception as e:
        print(f"Error fetching weather: {e}")
    
    return "N/A", "N/A"

def get_astro_data(date_str, lat=DEFAULT_LAT, lon=DEFAULT_LON):
    """
    Calculates astronomical data for the given date and location.
    Returns a formatted markdown string.
    """
    try:
        # Parse date
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Observer setup
        obs = ephem.Observer()
        obs.lat = lat
        obs.lon = lon
        obs.elevation = DEFAULT_ELEVATION
        
        # Determine UTC offset.
        # This is tricky without a timezone library like pytz or timezonefinder.
        # For now, we will stick to the hardcoded -5 (EST) approach for consistency with previous logic,
        # OR we could try to be smarter. 
        # Given the constraints and the journal nature (person likely in EST/EDT zone usually),
        # sticking to -5 is a safe fallback if we don't want to add heavy deps.
        # However, if location changes to say "London", -5 is wrong.
        # But `ephem` calculations for rise/set are done in UTC, and we convert to local.
        # If we don't know the local timezone offset of the arbitrary location, 
        # showing "Local Time" is hard.
        # For this iteration, let's keep assuming the user is documenting in their "Home" timezone (EST)
        # unless we want to over-engineer the timezone lookup.
        
        utc_offset = datetime.timedelta(hours=-5)
        
        # Start of day in UTC (approx, based on offset)
        start_local = datetime.datetime.combine(d, datetime.time(0, 0, 0))
        start_utc = start_local - utc_offset
        
        obs.date = start_utc
        
        sun = ephem.Sun()
        moon = ephem.Moon()
        
        def to_local_time_str(ephem_date):
            if not ephem_date: return "N/A"
            dt_utc = set_utc(ephem_date.datetime())
            dt_local = dt_utc + utc_offset
            # Check if it's still on the same local day
            if dt_local.date() != d:
                # It might be, or next day. Just return time.
                pass
            return dt_local.strftime("%H:%M:%S")

        def set_utc(dt):
            return dt.replace(tzinfo=datetime.timezone.utc)

        # Sun
        sun_rise = to_local_time_str(obs.next_rising(sun))
        sun_set = to_local_time_str(obs.next_setting(sun))
        
        # Moon
        moon_rise = to_local_time_str(obs.next_rising(moon))
        moon_set = to_local_time_str(obs.next_setting(moon))
        
        # Moon Phase at noon
        obs.date = start_utc + datetime.timedelta(hours=12)
        moon.compute(obs)
        phase_illum = moon.phase 
        phase_str = f"{phase_illum:.1f}%"
        
        return f"""
* Sunrise: {sun_rise or "N/A"}
* Sunset: {sun_set or "N/A"}
* Moonrise: {moon_rise or "N/A"}
* Moonset: {moon_set or "N/A"}
* Moon phase: {phase_str}
"""
    except Exception as e:
        print(f"Error calculating astro data: {e}")
        return ""

def process_image(image_path):
    print(f"Processing {image_path}...")
    
    if not os.path.exists(image_path):
        print(f"Error: File {image_path} not found.")
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Please set it with: export GEMINI_API_KEY='your_key'")
        return

    # 1. Setup paths
    filename = os.path.basename(image_path)
    base_name, ext = os.path.splitext(filename)
    today = datetime.date.today().isoformat()
    
    # Destination for image
    relative_img_dir = "static/images"
    dest_img_dir = os.path.join(os.getcwd(), relative_img_dir)
    os.makedirs(dest_img_dir, exist_ok=True)
    
    dest_image_name = f"{today}-{filename}"
    dest_image_path = os.path.join(dest_img_dir, dest_image_name)
    
    shutil.copy2(image_path, dest_image_path)
    print(f"Image saved to {dest_image_path}")

    # 2. Perform OCR with Gemini
    print("Initializing Gemini (google-genai) for OCR...")
    
    try:
        client = genai.Client(api_key=api_key)
        
        print("Reading text from image...")
        img = Image.open(image_path)
        
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=[
                "Transcribe the handwritten text in this image. This is a magickal journal entry. Rules: 1. Transcribe EXACTLY as written, including idiosyncratic spellings like 'candel', 'magick', 'sunrises'. 2. Format timestamps in double brackets as [[YYYY/MM/DD HH:MM:SS (EST|EDT)]]. 3. Do not add any conversational filler.", 
                img
            ]
        )
        transcribed_text = response.text.strip()
    except Exception as e:
        print(f"Error during OCR: {e}")
        transcribed_text = f"OCR Failed: {e}"
    
    print("Transcription complete.")
    print("-" * 20)
    print(transcribed_text)
    print("-" * 20)

    # 2.5 Parse Transcription and Insert Astro Data per Timestamp
    lines = transcribed_text.split('\n')
    processed_blocks = []
    current_block = []
    
    # Regex to find [[YYYY/MM/DD ...]]
    ts_pattern = re.compile(r'\[\[(\d{4}/\d{2}/\d{2})')

    def flush_block(block_lines):
        if not block_lines:
            return ""
        
        # Split first line into [[Timestamp]] and trailing text
        first_line = block_lines[0].strip()
        ts_split_pattern = re.compile(r'(\[\[\d{4}/\d{2}/\d{2}.*?\]\])(.*)')
        match = ts_split_pattern.match(first_line)
        
        if match:
            ts_full = match.group(1)
            date_captured = re.search(r'(\d{4}/\d{2}/\d{2})', ts_full).group(1)
            date_str = date_captured.replace('/', '-')
            trailing_text = match.group(2).strip()
            
            # Defaults
            lat = DEFAULT_LAT
            lon = DEFAULT_LON
            loc_name = DEFAULT_LOCATION_NAME
            
            # Scan for override
            lines_to_keep = []
            
            # Check trailing text first (rarely has location but possible)
            if trailing_text and trailing_text.startswith('* Location:'):
                 loc_val = trailing_text.split(':', 1)[1].strip()
                 if loc_val:
                     loc_name = loc_val
                     new_coords = get_coordinates_from_name(loc_name)
                     if new_coords:
                         lat, lon = new_coords
                 # Consume trailing text if it was just location? 
                 # Maybe dangerous if there is other text. 
                 # But usually bullet points are on new lines.
                 # Let's assume user puts bullets on new lines.
                 trailing_text = "" 

            # Check rest of lines
            for line in block_lines[1:]:
                clean = line.strip()
                if clean.startswith('* Location:'):
                    loc_val = clean.split(':', 1)[1].strip()
                    if loc_val:
                        loc_name = loc_val
                        new_coords = get_coordinates_from_name(loc_name)
                        if new_coords:
                            lat, lon = new_coords
                    # Don't add this line to lines_to_keep
                else:
                    lines_to_keep.append(line)

            # Fetch weather data
            dt_match = re.search(r'(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', ts_full)
            weather_block = ""
            if dt_match:
                y, m, d, H, M, S = map(int, dt_match.groups())
                dt = datetime.datetime(y, m, d, H, M, S)
                temp, condition = get_weather_data(dt, lat, lon)
                weather_block = f"* Location: {loc_name}\n* Temperature: {temp}\n* Weather Condition: {condition}\n"

            astro_data = get_astro_data(date_str, lat, lon).strip()
            
            # Combine
            meta_data = f"{weather_block}{astro_data}"
            
            bullets = []
            remainder = []
            
            if trailing_text:
                remainder.append(trailing_text)
                
            for line in lines_to_keep:
                clean = line.strip()
                if clean.startswith('*'):
                    bullets.append(clean)
                elif clean:
                    remainder.append(line)
            
            # Combine list items
            list_content = meta_data
            if bullets:
                list_content += "\n" + "\n".join(bullets)
            
            # Ensure blank line between timestamp and list
            final_section = f"{ts_full}\n\n{list_content}"
            
            if remainder:
                final_section += "\n\n" + "\n".join(remainder)
                
            return final_section
        else:
            return "\n".join(block_lines)


    for line in lines:
        if ts_pattern.match(line.strip()):
            if current_block:
                processed_blocks.append(flush_block(current_block))
                current_block = []
        current_block.append(line)
    
    if current_block:
        processed_blocks.append(flush_block(current_block))

    final_body = "\n\n".join(processed_blocks)

    # 3. Create Markdown Post
    posts_dir = os.path.join("content", "posts")
    os.makedirs(posts_dir, exist_ok=True)
    
    post_filename = f"{today}-{base_name}.md"
    post_path = os.path.join(posts_dir, post_filename)
    
    # Check if file exists to avoid overwrite? Or just overwrite? 
    # We'll append timestamp if it exists to be safe.
    if os.path.exists(post_path):
        timestamp = datetime.datetime.now().strftime("%H%M%S")
        post_filename = f"{today}-{base_name}-{timestamp}.md"
        post_path = os.path.join(posts_dir, post_filename)

    # Image URL for HTML (relative to the site root)
    img_url = f"static/images/{dest_image_name}"

    markdown_content = f"""
---
date: {today}
image: {img_url}
---

{final_body}

"""
    
    with open(post_path, 'w') as f:
        f.write(markdown_content)
    
    print(f"Post created at {post_path}")

    # 4. Rebuild Site
    print("Rebuilding site...")
    build.build()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python publish.py <path_to_image>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    process_image(image_path)
