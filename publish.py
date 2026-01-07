#!/usr/bin/env python3
import sys
import os
import shutil
import datetime
import math
import re
import time
import requests
import argparse
from google import genai
from google.genai import errors
from PIL import Image
import build
import ephem

# Default Coordinates (Kitchener, ON, Canada)
DEFAULT_LAT = '43.4254'
DEFAULT_LON = '-80.5112'
DEFAULT_ELEVATION = 300 # Approx for Kitchener
DEFAULT_LOCATION_NAME = "Kitchener, ON, Canada"

DEFAULT_MODELS = [
    'gemini-3-pro', 'gemini-3-pro-preview', 
    'gemini-3-flash', 'gemini-3-flash-preview', 
    'gemini-2.5-pro', 'gemini-2.5-flash', 
    'gemini-2.0-flash', 'gemini-2.5-flash-lite-preview-02-05', 
    'gemini-1.5-flash'
]

def generate_content_with_retry(client, models, contents, retries=1, failed_models=None):
    if isinstance(models, str):
        models = [models]
        
    for model in models:
        if failed_models and model in failed_models:
            print(f"Skipping known failed model: {model}")
            continue

        print(f"Trying model: {model}")
        for attempt in range(retries + 1):
            try:
                return client.models.generate_content(model=model, contents=contents)
            except errors.ClientError as e:
                if e.code == 429:
                    print(f"429 Resource Exhausted. Attempt {attempt + 1}/{retries + 1}")
                    delay = 60 # Default to 60s
                    
                    match = re.search(r'retry in (\d+(\.\d+)?)s', str(e))
                    if match:
                        delay = float(match.group(1)) + 2
                    
                    print(f"Sleeping for {delay:.2f}s before retrying...")
                    time.sleep(delay)
                    
                    if attempt == retries:
                        print(f"Max retries reached for model {model}.")
                        if failed_models is not None:
                            failed_models.add(model)
                        
                        if model == models[-1]:
                            print("All models failed.")
                            raise
                        else:
                            print("Switching to next model...")
                elif e.code == 404:
                    print(f"Model {model} not found (404). Skipping to next model.")
                    if failed_models is not None:
                        failed_models.add(model)
                    break
                else:
                    print(f"ClientError {e.code} with model {model}: {e}. Skipping to next model.")
                    if failed_models is not None:
                        failed_models.add(model)
                    break

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

def optimize_image(source_path, dest_dir, filename_base):
    """
    Optimizes image: converts to WebP, resizes to max width 1600px.
    Returns the new filename.
    """
    try:
        with Image.open(source_path) as img:
            # Fix orientation based on EXIF
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)

            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            max_width = 1600
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

            new_filename = f"{filename_base}.webp"
            dest_path = os.path.join(dest_dir, new_filename)
            
            img.save(dest_path, "WEBP", quality=80)
            print(f"Image optimized and saved to {dest_path}")
            return new_filename
    except Exception as e:
        print(f"Error optimizing image: {e}. Falling back to copy.")
        base, ext = os.path.splitext(source_path)
        new_filename = f"{filename_base}{ext}"
        dest_path = os.path.join(dest_dir, new_filename)
        shutil.copy2(source_path, dest_path)
        return new_filename

def process_image(image_path, models=None, failed_models=None):
    if models is None:
        models = DEFAULT_MODELS
        
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
    
    # Destination for image
    relative_img_dir = "static/images"
    dest_img_dir = os.path.join(os.getcwd(), relative_img_dir)
    os.makedirs(dest_img_dir, exist_ok=True)
    
    # We will determine final image name after we get the date
    # For now copy to temp or hold off? 
    # Actually, the original logic copied it immediately using 'today'. 
    # We should wait until we have the date from OCR to name the file correctly if we want YYYY-MM-DD-filename.
    # But OCR needs the image. 
    # Let's copy it to a temp name or just use the original name?
    # The user instruction implies "use the date of the first timestamp for the entry" -> likely for the post date/filename.
    # Does it apply to the image filename too? Probably consistency is good.
    # Let's do OCR on the source path first.
    
    # 2. Perform OCR with Gemini
    print("Initializing Gemini (google-genai) for OCR...")
    
    try:
        client = genai.Client(api_key=api_key)
        
        print("Reading text from image...")
        img = Image.open(image_path)
        
        response = generate_content_with_retry(
            client=client,
            models=models,
            contents=[
                "Transcribe the handwritten text in this image. This is a magickal journal entry. Rules: 1. Transcribe EXACTLY as written, including idiosyncratic spellings like 'candel', 'magick', 'sunrises'. 2. Format timestamps in double brackets with exactly one space after [[ and before ]], like this: [[ YYYY/MM/DD HH:MM:SS EST ]]. Pay close attention to the time digits. If you see a 'T' between the date and time, ignore it and use a space. 3. Do not add any conversational filler. 4. If you see text in double quotes like \"\"TITLE\"\", remove the quotes and place the TITLE text immediately before the timestamp on the same line, like: TITLE [[ YYYY/... ]].", 
                img
            ],
            failed_models=failed_models
        )
        transcribed_text = response.text.strip()
        
        # 2.1 Perform Spell Check with Gemini
        if not transcribed_text.startswith("OCR Failed:"):
            print("Performing spell check...")
            try:
                spell_check_prompt = (
                    "You are a spell checker for a transcription of a handwritten journal. "
                    "Your goal is to correct any clear spelling errors (like typos or missing letters) while preserving the original context. "
                    "If a word is spelled correctly, or if it is an intentional variant common in magickal journals (like 'magick'), leave it as is. "
                    "Provide the corrected text directly. Do NOT use any special notation like {{OriginalWord}} to highlight changes. "
                    "Preserve all formatting, including timestamps which MUST be in the format [[ YYYY/MM/DD HH:MM:SS TZ ]] (with exactly one space after [[ and before ]]) and any bullet points. "
                    "Do not add any conversational filler. Only output the corrected text."
                )
                
                spell_check_response = generate_content_with_retry(
                    client=client,
                    models=models,
                    contents=[spell_check_prompt, transcribed_text],
                    failed_models=failed_models
                )
                transcribed_text = spell_check_response.text.strip()
            except Exception as e:
                print(f"Error during spell check: {e}")
    except Exception as e:
        print(f"Error during OCR: {e}")
        transcribed_text = f"OCR Failed: {e}"
    
    print("Transcription (and spell check) complete.")
    print("-" * 20)
    print(transcribed_text)
    print("-" * 20)
    
    # Extract date from first timestamp
    post_date = datetime.date.today()
    ts_match = re.search(r'\[\[\s*(\d{4}/\d{2}/\d{2})', transcribed_text)
    if ts_match:
        try:
            date_str = ts_match.group(1).replace('/', '-')
            post_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            print(f"Detected date from timestamp: {post_date}")
        except ValueError:
            print("Error parsing date from timestamp, defaulting to today.")
    
    post_date_str = post_date.isoformat()
    
    # Now we can name the image and post
    # dest_image_name = f"{post_date_str}-{filename}" # Old way
    
    dest_image_name = optimize_image(image_path, dest_img_dir, f"{post_date_str}-{base_name}")
    dest_image_path = os.path.join(dest_img_dir, dest_image_name) # For reference if needed

    # 2.5 Parse Transcription and Insert Astro Data per Timestamp
    lines = transcribed_text.split('\n')
    processed_blocks = []
    current_block = []
    
    # Regex to find [[ YYYY/MM/DD ... ]] - allowing optional leading bullet/space
    # Also support space delimiters in date YYYY MM DD
    ts_pattern = re.compile(r'.*?\[\[\s*(\d{4}[/ ]\d{2}[/ ]\d{2})')

    def flush_block(block_lines):
        if not block_lines:
            return ""
        
        # Split first line into [[ Timestamp ]] and trailing text
        first_line = block_lines[0].strip()
        # Pattern to capture optional prefix/bullet, the timestamp (flexible), and then trailing text
        ts_split_pattern = re.compile(r'^(.*?)(\[\[\s*\d{4}[/ ]\d{2}[/ ]\d{2}.*?\s*\]\])(.*)')
        match = ts_split_pattern.match(first_line)
        
        if match:
            prefix = match.group(1)
            ts_full = match.group(2)
            
            # Extract date
            date_captured_match = re.search(r'(\d{4})[/ ](\d{2})[/ ](\d{2})', ts_full)
            if date_captured_match:
                y, m, d = int(date_captured_match.group(1)), int(date_captured_match.group(2)), int(date_captured_match.group(3))
                date_obj = datetime.date(y, m, d)
                date_str = date_obj.isoformat()
                day_of_week = date_obj.strftime('%A')
            else:
                date_obj = datetime.date.today()
                date_str = date_obj.isoformat()
                day_of_week = date_obj.strftime('%A')

            trailing_text = match.group(3).strip()
            
            # Defaults
            lat = DEFAULT_LAT
            lon = DEFAULT_LON
            loc_name = DEFAULT_LOCATION_NAME
            
            # Scan for override
            lines_to_keep = []
            
            def is_location_line(text):
                return text.strip().startswith(('* Location:', '- Location:', '• Location:'))

            # Check trailing text first (rarely has location but possible)
            if trailing_text and is_location_line(trailing_text):
                 loc_val = trailing_text.split(':', 1)[1].strip()
                 if loc_val:
                     loc_name = loc_val
                     new_coords = get_coordinates_from_name(loc_name)
                     if new_coords:
                         lat, lon = new_coords
                 trailing_text = "" 

            # Check rest of lines
            for line in block_lines[1:]:
                if is_location_line(line):
                    loc_val = line.strip().split(':', 1)[1].strip()
                    if loc_val:
                        loc_name = loc_val
                        new_coords = get_coordinates_from_name(loc_name)
                        if new_coords:
                            lat, lon = new_coords
                else:
                    lines_to_keep.append(line)

            # Fetch weather data
            dt_match = re.search(r'(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', ts_full)
            weather_block = ""
            if dt_match:
                y, m, d, H, M, S = map(int, dt_match.groups())
                dt = datetime.datetime(y, m, d, H, M, S)
                temp, condition = get_weather_data(dt, lat, lon)
                weather_block = f"  * Location: {loc_name}\n  * Temperature: {temp}\n  * Weather Condition: {condition}\n"

            astro_data = get_astro_data(date_str, lat, lon).strip()
            
            # Combine
            meta_data = f"{weather_block}{astro_data}\n  * Day of Week: {day_of_week}"
            
            bullets = []
            remainder = []
            
            def is_bullet(text):
                t = text.strip()
                return t.startswith(('*', '-', '•'))

            if trailing_text:
                if is_bullet(trailing_text):
                    bullets.append(trailing_text.strip())
                else:
                    remainder.append(trailing_text)
                
            for line in lines_to_keep:
                if is_bullet(line):
                    bullets.append(line.strip())
                elif line.strip():
                    remainder.append(line)
            
            # Combine list items
            list_content = meta_data
            if bullets:
                if list_content and not list_content.endswith('\n'):
                    list_content += "\n"
                list_content += "\n".join("  " + b for b in bullets)
            
            # Ensure blank line between timestamp and list
            final_section = f"{prefix}{ts_full}\n\n{list_content.strip()}"
            
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
    
    post_filename = f"{post_date_str}-{base_name}.md"
    post_path = os.path.join(posts_dir, post_filename)
    
    # Check if file exists to avoid overwrite? Or just overwrite? 
    # We'll append timestamp if it exists to be safe.
    if os.path.exists(post_path):
        timestamp = datetime.datetime.now().strftime("%H%M%S")
        post_filename = f"{post_date_str}-{base_name}-{timestamp}.md"
        post_path = os.path.join(posts_dir, post_filename)

    # Image URL for HTML (relative to the site root)
    img_url = f"static/images/{dest_image_name}"

    # Check for future date (using the extracted post_date)
    is_future = False
    if post_date > datetime.date.today():
        is_future = True
        print(f"Warning: Extracted date {post_date} is in the future!")

    markdown_content = f"""
---
date: {post_date_str}
image: {img_url}
future: {str(is_future).lower()}
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
    parser = argparse.ArgumentParser(description="Publish a new journal entry from an image.")
    parser.add_argument("image_path", nargs="?", help="Path to the image to process.")
    parser.add_argument("-l", "--list-models", action="store_true", help="List available models and exit.")
    parser.add_argument("-m", "--model", help="Start with this model, skipping those before it in the list.")
    
    args = parser.parse_args()
    
    if args.list_models:
        print("Available models:")
        for model in DEFAULT_MODELS:
            print(f"  - {model}")
        sys.exit(0)
        
    if not args.image_path:
        parser.error("image_path is required unless --list-models is specified.")
    
    models = DEFAULT_MODELS
    if args.model:
        if args.model in models:
            idx = models.index(args.model)
            models = models[idx:]
            print(f"Starting with model: {args.model}")
        else:
            print(f"Warning: Model '{args.model}' not found in default list. Using it as a custom single model.")
            models = [args.model]

    process_image(args.image_path, models=models)
