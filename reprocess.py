#!/usr/bin/env python3
import sys
import os
import re
import datetime
from google import genai
from PIL import Image
import publish
import build

def reprocess(post_path, image_path):
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

    # 1. Perform OCR (copied logic from publish.py but we want to return the text)
    client = genai.Client(api_key=api_key)
    img = Image.open(image_path)
    
        print("Running Gemini OCR...")
    
        response = client.models.generate_content(
    
            model='gemini-2.5-flash-lite',
    
            contents=[
    
                "Transcribe the handwritten text in this image. This is a magickal journal entry. Rules: 1. Transcribe EXACTLY as written, including idiosyncratic spellings like 'candel', 'magick', 'sunrises'. 2. Format timestamps in double brackets with spaces as [[ YYYY/MM/DD HH:MM:SS EST ]] or [[ YYYY/MM/DD HH:MM:SS EDT ]]. Do NOT use parentheses around the timezone. Pay close attention to the time digits. 3. Do not add any conversational filler.", 
    
                img
    
            ]
    
        )
    
        transcribed_text = response.text.strip()
    
        
    
        print("Running Gemini Spell Check...")
    
        spell_check_prompt = (
    
            "You are a spell checker for a transcription of a handwritten journal. "
    
            "Your goal is to correct any clear spelling errors (like typos or missing letters) while preserving the original context. "
    
            "If a word is spelled correctly, or if it is an intentional variant common in magickal journals (like 'magick'), leave it as is. "
    
            "Provide the corrected text directly. Do NOT use any special notation like {{OriginalWord}} to highlight changes. "
    
            "Preserve all formatting, including double brackets with spaces for timestamps [[ YYYY/MM/DD HH:MM:SS TZ ]] and any bullet points. "
    
            "Do not add any conversational filler. Only output the corrected text."
    
        )
    
        spell_check_response = client.models.generate_content(
    
            model='gemini-2.5-flash',
    
            contents=[spell_check_prompt, transcribed_text]
    
        )
    
        transcribed_text = spell_check_response.text.strip()
    
    
    
        # 2. Process blocks (using logic from publish.py)
    
        # We need to reach into publish.py's internal logic or duplicate it.
    
        # Since I can't easily import the nested functions, I'll use publish.process_image's logic
    
        # but instead of creating a NEW post, we update the existing one.
    
        
    
        # We can fake a partial 'publish' run by mocking some parts if needed, 
    
        # but it's safer to just extract the core transformation.
    
        
    
        # Let's use the same logic as publish.py to get the 'final_body'
    
        lines = transcribed_text.split('\n')
    
        processed_blocks = []
    
        current_block = []
    
        ts_pattern = re.compile(r'^[*•-]?\s*\[\[\s*(\d{4}/\d{2}/\d{2})')
    
    
    
        # I'll just use the same code as in publish.py since I can't easily call flush_block
    
        def flush_block_local(block_lines):
    
            if not block_lines: return ""
    
            first_line = block_lines[0].strip()
    
            ts_split_pattern = re.compile(r'^([*•-]?\s*)(\[\[\s*\d{4}/\d{2}/\d{2}.*?\s*\]\])(.*)')
    
            match = ts_split_pattern.match(first_line)
    
            if match:
    
                ts_full = match.group(2)
    
                date_captured = re.search(r'(\d{4}/\d{2}/\d{2})', ts_full).group(1)
    
                date_str = date_captured.replace('/', '-')
    
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
    
    
    
                dt_match = re.search(r'(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', ts_full)
    
                weather_block = ""
    
                if dt_match:
    
                    y, m, d, H, M, S = map(int, dt_match.groups())
    
                    dt = datetime.datetime(y, m, d, H, M, S)
    
                    temp, condition = publish.get_weather_data(dt, lat, lon)
    
                    weather_block = f"  * Location: {loc_name}\n  * Temperature: {temp}\n  * Weather Condition: {condition}\n"
    
    
    
                astro_data = publish.get_astro_data(date_str, lat, lon).strip()
    
                meta_data = f"{weather_block}{astro_data}"
    
                
    
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
    
                
    
                final_section = f"{ts_full}\n\n{list_content.strip()}"
    
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
    
            
    
            first_ts_match = re.search(r'\[\[\s*(\d{4}/\d{2}/\d{2})', final_body)
    
    
                if first_ts_match:
                    ts_date_str = first_ts_match.group(1).replace('/', '-')
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
                
                # Note: If date wasn't found in frontmatter, we usually don't add it blindly 
                # unless we are sure, but existing posts should have it.
                
                new_frontmatter = "\n".join(new_lines)
                new_content = f"---{new_frontmatter}---\n\n{final_body}\n"
        with open(post_path, 'w') as f:
            f.write(new_content)
        print(f"Updated {post_path}")
    else:
        print("Error: Could not parse frontmatter from old post.")

    # 4. Rebuild
    build.build(force=True)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Reprocess an existing post using OCR on a specified image.')
    parser.add_argument('post_path', help='Path to the existing markdown post to update')
    parser.add_argument('image_path', help='Path to the source image to OCR')
    
    args = parser.parse_args()
    reprocess(args.post_path, args.image_path)
