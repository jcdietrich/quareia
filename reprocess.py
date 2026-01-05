#!/usr/bin/env python3
import sys
import os
import re
import datetime
import time
from google import genai
from google.genai import errors
from PIL import Image
import publish
import build

def generate_content_with_retry(client, model, contents, retries=3):
    # Note: This local function seems to take a single 'model' string, not a list.
    # But for consistency with the robust logic, we should probably handle it similarly if we were using it.
    # However, to keep the signature compatible with existing calls (if any exist that use this local one),
    # I will keep the signature but add the error handling.
    # Wait, the local function signature in reprocess.py was: def generate_content_with_retry(client, model, contents, retries=3):
    # It takes 'model' (singular). 
    
    for attempt in range(retries + 1):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except errors.ClientError as e:
            if e.code == 429:
                print(f"429 Resource Exhausted. Attempt {attempt + 1}/{retries + 1}")
                delay = 60 # Default to 60s
                
                # Extract retry delay from error message
                match = re.search(r'retry in (\d+(\.\d+)?)s', str(e))
                if match:
                    delay = float(match.group(1)) + 2 # Add 2s buffer
                
                print(f"Sleeping for {delay:.2f}s before retrying...")
                time.sleep(delay)
                
                if attempt == retries:
                    print("Max retries reached.")
                    raise
            elif e.code == 404:
                 print(f"Model {model} not found (404).")
                 raise # Since we only have one model here, we must raise.
            else:
                print(f"ClientError {e.code}: {e}")
                raise

def reprocess(post_path, image_path, models=None, failed_models=None):
    if models is None:
        models = publish.DEFAULT_MODELS

    print(f"Reprocessing {post_path} using {image_path}...")
    
    if not post_path.endswith('.md'):
        print(f"Error: First argument '{post_path}' does not look like a markdown file (.md).")
        print("Usage: python reprocess.py <post_path> <image_path>")
        return

    if not os.path.exists(post_path):
        print(f"Error: Post {post_path} not found.")
        return
    if not os.path.exists(image_path):
        print(f"Error: Image {image_path} not found.")
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return

    # 1. Perform OCR
    client = genai.Client(api_key=api_key)
    img = Image.open(image_path)
    
    print("Running Gemini OCR...")
    response = publish.generate_content_with_retry(
        client=client,
        models=models,
        contents=[
            "Transcribe the handwritten text in this image. This is a magickal journal entry. Rules: 1. Transcribe EXACTLY as written, including idiosyncratic spellings like 'candel', 'magick', 'sunrises'. 2. Format timestamps in double brackets with exactly one space after [[ and before ]], like this: [[ YYYY/MM/DD HH:MM:SS EST ]]. Pay close attention to the time digits. If you see a 'T' between the date and time, ignore it and use a space. 3. Do not add any conversational filler. 4. If you see text in double quotes like \"\"TITLE\"\", remove the quotes and place the TITLE text immediately before the timestamp on the same line, like: TITLE [[ YYYY/... ]].", 
            img
        ],
        failed_models=failed_models
    )
    transcribed_text = response.text.strip()
    
    print("Running Gemini Spell Check...")
    spell_check_prompt = (
        "You are a spell checker for a transcription of a handwritten journal. "
        "Your goal is to correct any clear spelling errors (like typos or missing letters) while preserving the original context. "
        "If a word is spelled correctly, or if it is an intentional variant common in magickal journals (like 'magick'), leave it as is. "
        "Provide the corrected text directly. Do NOT use any special notation like {{OriginalWord}} to highlight changes. "
        "Preserve all formatting, including timestamps which MUST be in the format [[ YYYY/MM/DD HH:MM:SS TZ ]] (with exactly one space after [[ and before ]]) and any bullet points. "
        "Do not add any conversational filler. Only output the corrected text."
    )
    spell_check_response = publish.generate_content_with_retry(
        client=client,
        models=models,
        contents=[spell_check_prompt, transcribed_text],
        failed_models=failed_models
    )
    transcribed_text = spell_check_response.text.strip()

    # 2. Process blocks
    lines = transcribed_text.split('\n')
    processed_blocks = []
    current_block = []
    
    # Regex to find [[ YYYY/MM/DD ... ]] - allowing optional leading bullet/space
    # Also support space delimiters in date YYYY MM DD
    ts_pattern = re.compile(r'.*?\[[\\\]\s*(\d{4}[/ ]\d{2}[/ ]\d{2})')

    def flush_block_local(block_lines):
        if not block_lines: return ""
        first_line = block_lines[0].strip()
        # Regex to capture prefix, timestamp (flexible delimiters), and trailing text
        ts_split_pattern = re.compile(r'^(.*?)(\[[\\\]\s*\d{4}[/ ]\d{2}[/ ]\d{2}.*?\s*\]\])(.*)')
        match = ts_split_pattern.match(first_line)
        if match:
            prefix = match.group(1)
            ts_full = match.group(2)
            
            # Extract date for processing
            date_captured_match = re.search(r'(\d{4})[/ ](\d{2})[/ ](\d{2})', ts_full)
            if date_captured_match:
                # Create a date object to get the day of week
                y, m, d = int(date_captured_match.group(1)), int(date_captured_match.group(2)), int(date_captured_match.group(3))
                date_obj = datetime.date(y, m, d)
                date_str = date_obj.isoformat()
                day_of_week = date_obj.strftime('%A') # Full day name (e.g., Monday)
            else:
                date_obj = datetime.date.today()
                date_str = date_obj.isoformat()
                day_of_week = date_obj.strftime('%A')

            trailing_text = match.group(3).strip()
            
            lat = publish.DEFAULT_LAT
            lon = publish.DEFAULT_LON
            loc_name = publish.DEFAULT_LOCATION_NAME
            
            lines_to_keep = []
            def is_location_line(text):
                return text.strip().startswith(('* Location:', '- Location:', '• Location:'))

            if trailing_text and is_location_line(trailing_text):
                 loc_val = trailing_text.split(':', 1)[1].strip()
                 if loc_val:
                     loc_name = loc_val
                     new_coords = publish.get_coordinates_from_name(loc_name)
                     if new_coords: lat, lon = new_coords
                 trailing_text = "" 

            for line in block_lines[1:]:
                if is_location_line(line):
                    loc_val = line.strip().split(':', 1)[1].strip()
                    if loc_val:
                        loc_name = loc_val
                        new_coords = publish.get_coordinates_from_name(loc_name)
                        if new_coords: lat, lon = new_coords
                else:
                    lines_to_keep.append(line)

            dt_match = re.search(r'(\d{4})[/ ](\d{2})[/ ](\d{2})\s+(\d{2}):(\d{2}):(\d{2})', ts_full)
            weather_block = ""
            if dt_match:
                y, m, d, H, M, S = map(int, dt_match.groups())
                dt = datetime.datetime(y, m, d, H, M, S)
                temp, condition = publish.get_weather_data(dt, lat, lon)
                weather_block = f"  * Location: {loc_name}\n  * Temperature: {temp}\n  * Weather Condition: {condition}\n"

            astro_data = publish.get_astro_data(date_str, lat, lon).strip()
            # Insert Day of Week
            meta_data = f"{weather_block}{astro_data}\n  * Day of Week: {day_of_week}"
            
            bullets = []
            remainder = []
            def is_bullet(text):
                t = text.strip()
                return t.startswith(('*', '-', '•'))

            if trailing_text:
                if is_bullet(trailing_text): bullets.append(trailing_text.strip())
                else: remainder.append(trailing_text)
                
            for line in lines_to_keep:
                if is_bullet(line): bullets.append(line.strip())
                elif line.strip(): remainder.append(line)
            
            list_content = meta_data
            if bullets:
                if list_content and not list_content.endswith('\n'): list_content += "\n"
                list_content += "\n".join("  " + b for b in bullets)
            
            final_section = f"{prefix}{ts_full}\n\n{list_content.strip()}"
            if remainder: final_section += "\n\n" + "\n".join(remainder)
            return final_section
        else:
            return "\n".join(block_lines)

    for line in lines:
        if ts_pattern.match(line.strip()):
            if current_block:
                processed_blocks.append(flush_block_local(current_block))
                current_block = []
        current_block.append(line)
    if current_block:
        processed_blocks.append(flush_block_local(current_block))

    final_body = "\n\n".join(processed_blocks)

    # 3. Update the post file
    with open(post_path, 'r') as f:
        old_content = f.read()

    # Split frontmatter
    parts = old_content.split('---', 2)
    if len(parts) >= 3:
        frontmatter_raw = parts[1]
        
        # Check for future date in the new body
        is_future = False
        extracted_date = None
        
        first_ts_match = re.search(r'\[[\\\]\s*(\d{4}[/ ]\d{2}[/ ]\d{2})', final_body)
        if first_ts_match:
            # Handle potential space delimiters in captured date for parsing
            raw_date_str = first_ts_match.group(1)
            norm_date_str = raw_date_str.replace(' ', '-')
            ts_date_str = norm_date_str.replace('/', '-')
            extracted_date = datetime.datetime.strptime(ts_date_str, "%Y-%m-%d").date()
            if extracted_date > datetime.date.today():
                is_future = True
                print(f"Warning: Extracted date {extracted_date} is in the future!")
        
        # Update or add 'future' key and 'date' key in frontmatter
        lines = frontmatter_raw.strip().split('\n')
        new_lines = []
        future_found = False
        date_found = False
        
        for line in lines:
            if line.startswith('future:'):
                new_lines.append(f"future: {str(is_future).lower()}")
                future_found = True
            elif line.startswith('date:') and extracted_date:
                new_lines.append(f"date: {extracted_date.isoformat()}")
                date_found = True
            else:
                new_lines.append(line)
        
        if not future_found:
            new_lines.append(f"future: {str(is_future).lower()}")
        
        new_frontmatter = "\n".join(new_lines)
        new_content = f"---\n{new_frontmatter}\n---\n\n{final_body}\n"
        with open(post_path, 'w') as f:
            f.write(new_content)
        print(f"Updated {post_path}")
    else:
        print("Error: Could not parse frontmatter from old post.")

    # 4. Rebuild
    build.build(force=True)

if __name__ == "__main__":
    import argparse
    import glob
    
    parser = argparse.ArgumentParser(description='Reprocess existing posts using OCR on their associated images.')
    parser.add_argument('post_path', nargs='?', help='Path to the existing markdown post to update (optional if --all is used)')
    parser.add_argument('image_path', nargs='?', help='Path to the source image to OCR (optional if --all is used)')
    parser.add_argument('-a', '--all', action='store_true', help='Reprocess ALL posts in content/posts/')
    parser.add_argument('-d', '--date', help='Reprocess all posts from this date forward (inclusive). Format: YYYY-MM-DD.')
    parser.add_argument('-l', '--latest', action='store_true', help='Reprocess only the latest post.')
    parser.add_argument('--list-models', action='store_true', help='List available models and exit.')
    parser.add_argument('-m', '--model', help='Start with this model, skipping those before it in the list.')
    
    args = parser.parse_args()

    if args.list_models:
        print("Available models:")
        for model in publish.DEFAULT_MODELS:
            print(f"  - {model}")
        sys.exit(0)
    
    models = publish.DEFAULT_MODELS
    if args.model:
        if args.model in models:
            idx = models.index(args.model)
            models = models[idx:]
            print(f"Starting with model: {args.model}")
        else:
            print(f"Warning: Model '{args.model}' not found in default list. Using it as a custom single model.")
            models = [args.model]
    
    failed_models = set()

    target_date = None
    if args.date:
        try:
            target_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print("Error: Date format must be YYYY-MM-DD")
            sys.exit(1)

    if args.all or args.date or args.latest:
        posts_dir = 'content/posts'
        if not os.path.exists(posts_dir):
            print(f"Error: {posts_dir} does not exist.")
            sys.exit(1)
            
        md_files = glob.glob(os.path.join(posts_dir, '*.md'))
        md_files.sort() # Sort by filename (date)
        
        if args.latest and md_files:
            md_files = [md_files[-1]]
            print(f"Found latest post: {md_files[0]}")
        elif args.latest:
            print("No posts found to reprocess.")
            sys.exit(0)

        print(f"Found {len(md_files)} posts to process.")
        
        count = 0
        for post_file in md_files:
            if target_date:
                filename = os.path.basename(post_file)
                match = re.match(r'^(\d{4}-\d{2}-\d{2})', filename)
                if match:
                    file_date = datetime.datetime.strptime(match.group(1), "%Y-%m-%d").date()
                    if file_date < target_date:
                        continue
                else:
                    # If date filtering is on, skip files without date
                    continue
            
            count += 1
            # We need to find the image path from the post content
            try:
                with open(post_file, 'r') as f:
                    content = f.read()
                
                # Simple parsing for image: path
                image_match = re.search(r'^image:\s*(.*)', content, re.MULTILINE)
                if image_match:
                    img_rel_path = image_match.group(1).strip()
                    # image path in md is usually relative to site root (static/images/...)
                    # our script expects path relative to CWD
                    if os.path.exists(img_rel_path):
                        print(f"\n--- Reprocessing {post_file} ---")
                        reprocess(post_file, img_rel_path, models=models, failed_models=failed_models)
                        # Sleep to avoid rate limits (2 calls per reprocess)
                        if len(md_files) > 1:
                            time.sleep(10)
                    else:
                        print(f"Warning: Image {img_rel_path} not found for {post_file}, skipping.")
                else:
                    print(f"Warning: No image found in frontmatter for {post_file}, skipping.")
            except Exception as e:
                print(f"Error processing {post_file}: {e}")
        
        if count == 0 and args.date:
            print(f"No posts found from {args.date} onwards.")
                
    else:
        if not args.post_path or not args.image_path:
            parser.error("post_path and image_path are required unless --all, --date, or --latest is specified.")
        
        reprocess(args.post_path, args.image_path, models=models, failed_models=failed_models)