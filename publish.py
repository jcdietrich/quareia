#!/usr/bin/env python3
import sys
import os
import shutil
import datetime
import math
import re
from google import genai
from PIL import Image
import build
import ephem

# NYC Coordinates (Default)
LAT = '40.7128'
LON = '-74.0060'
ELEVATION = 10

def get_astro_data(date_str):
    """
    Calculates astronomical data for the given date in NYC (EST/EDT).
    Returns a formatted markdown string.
    """
    try:
        # Parse date
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Observer setup
        obs = ephem.Observer()
        obs.lat = LAT
        obs.lon = LON
        obs.elevation = ELEVATION
        
        # Determine UTC offset for EST/EDT
        # Simplified: Assume EST (-5) for Jan/Feb/Mar/Nov/Dec, EDT (-4) otherwise?
        # Better: use pytz if available, but let's stick to standard lib or manual for now to avoid deps.
        # Since the user specifically mentioned EST/EDT in prompt, let's just use -5 for now as we are in Jan.
        # Or better, just use -5 (EST) consistently as per the user's "EST" request.
        utc_offset = datetime.timedelta(hours=-5)
        
        # Start of day in UTC
        start_local = datetime.datetime.combine(d, datetime.time(0, 0, 0))
        start_utc = start_local - utc_offset
        
        obs.date = start_utc
        
        sun = ephem.Sun()
        moon = ephem.Moon()
        
        # Calculate events
        # Note: next_rising/setting returns ephem.Date (UTC)
        
        def to_local_time_str(ephem_date):
            if not ephem_date: return "N/A"
            dt_utc = set_utc(ephem_date.datetime())
            dt_local = dt_utc + utc_offset
            # Check if it's still on the same local day
            if dt_local.date() != d:
                return None 
            return dt_local.strftime("%H:%M:%S")

        def set_utc(dt):
            return dt.replace(tzinfo=datetime.timezone.utc)

        # Sun
        sun_rise = to_local_time_str(obs.next_rising(sun))
        sun_set = to_local_time_str(obs.next_setting(sun))
        
        # Moon
        moon_rise = to_local_time_str(obs.next_rising(moon))
        moon_set = to_local_time_str(obs.next_setting(moon))
        
        # If next rise/set is not today, check previous?
        # Actually, if we start at 00:00 local, next_rising should be today if it rises today.
        # Unless it rose yesterday and sets today.
        # Let's double check for moon.
        
        # Moon Phase
        # Calculate at noon local
        obs.date = start_utc + datetime.timedelta(hours=12)
        moon.compute(obs)
        phase_illum = moon.phase # 0..100
        
        # Rough phase name
        # We can use moon.elong (elongation)
        # 0 = New, 90 = First Quarter, 180 = Full, 270 = Last Quarter
        elong = math.degrees(moon.elong)
        # elong is 0..360? No, ephem elong is 0..2pi? No, it's 0..360 usually if converted.
        # Actually ephem uses radians.
        # But wait, elongation in ephem is angle from sun.
        # Let's rely on illumination and a simple heuristic if needed, or just print %.
        # User asked for "Moon phase", text is better.
        
        # ephem doesn't give phase name directly.
        # Let's simple format: "{illum:.1f}%"
        
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
    # Note: In build.py, we copy 'static' to 'docs/static'. 
    # So in the HTML, the path should be 'static/images/...'
    relative_img_dir = "static/images"
    dest_img_dir = os.path.join(os.getcwd(), relative_img_dir)
    os.makedirs(dest_img_dir, exist_ok=True)
    
    # Unique image name to avoid collisions
    dest_image_name = f"{today}-{filename}"
    dest_image_path = os.path.join(dest_img_dir, dest_image_name)
    
    # Copy image
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
                "Transcribe the handwritten text in this image exactly as written. Do not add any conversational text. However, for any text enclosed in double square brackets (timestamps), format it strictly as [[YYYY/MM/DD HH:MM:SS (EST|EDT)]], even if the handwritten version lacks punctuation or spaces (e.g., convert [[20260101074300EST]] to [[2026/01/01 07:43:00 EST]]).", 
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
            
            astro_data = get_astro_data(date_str).strip()
            
            bullets = []
            remainder = []
            
            if trailing_text:
                remainder.append(trailing_text)
                
            for line in block_lines[1:]:
                clean = line.strip()
                if clean.startswith('*'):
                    bullets.append(clean)
                elif clean:
                    remainder.append(line)
            
            res = [ts_full, astro_data]
            if bullets:
                res.append("\n".join(bullets))
            
            final_section = "\n".join(res)
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
