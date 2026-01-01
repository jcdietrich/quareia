#!/usr/bin/env python3
import os
import shutil
import markdown
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# Configuration
CONTENT_DIR = 'content/posts'
OUTPUT_DIR = 'docs'
TEMPLATE_DIR = 'templates'
STATIC_DIR = 'static'

def parse_post(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Simple frontmatter parser
    frontmatter = {}
    body = content
    
    # Strip leading whitespace for the check
    if content.lstrip().startswith('---'):
        # Split on the *first* two occurrences of ---
        # We need to be careful not to strip *too* much if we split on raw content
        # But for '---' splitting, using the original content is safer if we just find the indices.
        # Alternatively, just use the split logic on the stripped content if we don't mind losing leading newlines in body.
        
        parts = content.lstrip().split('---', 2)
        if len(parts) >= 3:
            raw_fm = parts[1]
            body = parts[2]
            for line in raw_fm.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    frontmatter[key.strip()] = value.strip()

    # Add <hr/> before second and subsequent timestamps
    timestamp_pattern = r'(\[\[\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} \(?[A-Z]{3}\)?\]\])'
    parts = re.split(timestamp_pattern, body)
    if len(parts) > 3:
        # parts[0] is text before 1st timestamp
        # parts[1] is 1st timestamp
        # parts[2] is text after 1st timestamp
        new_body = parts[0] + parts[1] + "\n\n" + parts[2].lstrip('\n')
        for i in range(3, len(parts), 2):
            # parts[i] is the i-th timestamp
            # parts[i+1] is text after it
            new_body += "\n\n---\n\n" + parts[i] + "\n\n" + parts[i+1].lstrip('\n')
        body = new_body

    html_content = markdown.markdown(body, extensions=['extra'])
    
    # Infer date/title if missing
    filename = os.path.basename(filepath)
    if 'date' not in frontmatter:
        # Try to parse from filename YYYY-MM-DD
        match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
        if match:
            frontmatter['date'] = match.group(1)
        else:
            frontmatter['date'] = datetime.now().strftime('%Y-%m-%d')

    if 'title' not in frontmatter:
        frontmatter['title'] = frontmatter['date']
            
    return {
        'metadata': frontmatter,
        'content': html_content,
        'filename': filename,
        'url': filename.replace('.md', '.html')
    }

def build():
    # Setup output directory
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    
    # Copy static assets
    if os.path.exists(STATIC_DIR):
        shutil.copytree(STATIC_DIR, os.path.join(OUTPUT_DIR, 'static'))

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    post_template = env.get_template('post.html')
    index_template = env.get_template('index.html')

    posts_by_date = {}
    build_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S EST')
    
    if os.path.exists(CONTENT_DIR):
        files = [f for f in os.listdir(CONTENT_DIR) if f.endswith('.md')]
        
        for file in files:
            filepath = os.path.join(CONTENT_DIR, file)
            post = parse_post(filepath)
            date = post['metadata'].get('date')
            
            if date not in posts_by_date:
                posts_by_date[date] = {
                    'title': date,
                    'date': date,
                    'entries': [],
                    'url': f"{date}.html"
                }
            
            # Determine sort key (first timestamp)
            # Regex to find [[YYYY/MM/DD HH:MM:SS ...]]
            # We look in the original raw content (which is not returned by parse_post, but we can re-read or modify parse_post)
            # Actually parse_post processes content into HTML. We can try to find it in HTML or better, modify parse_post to return raw body or extraction.
            # But let's just grep the file again or use a simple heuristic on the HTML or filename.
            # Reading the file again is cheap enough for now.
            with open(filepath, 'r') as f:
                raw_content = f.read()
            
            ts_match = re.search(r'\[\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', raw_content)
            if ts_match:
                sort_key = ts_match.group(1)
            else:
                # Fallback to a high string if not found, or low? 
                # If it's a tech note without timestamp, it might be an issue.
                # Use filename as fallback
                sort_key = "9999/99/99 99:99:99" 

            is_tech = file.endswith('-tech.md')
            
            posts_by_date[date]['entries'].append({
                'content': post['content'],
                'image': post['metadata'].get('image'),
                'sort_key': sort_key,
                'is_tech': is_tech,
                'filename': file
            })

    # Render pages and prepare index
    sorted_dates = sorted(posts_by_date.keys(), reverse=True)
    index_posts = []

    for date in sorted_dates:
        group = posts_by_date[date]
        
        # Sort entries: Tech last, then by timestamp
        group['entries'].sort(key=lambda x: (x['is_tech'], x['sort_key'], x['filename']))
        
        # Collect images for index (first one)
        first_image = next((e['image'] for e in group['entries'] if e['image']), '')
        
        index_posts.append({
            'title': group['title'],
            'date': group['date'],
            'url': group['url'],
            'image': first_image
        })
        
        # Render daily page
        output_html = post_template.render(
            title=group['title'],
            date=group['date'],
            entries=group['entries'],
            build_time=build_time
        )
        
        with open(os.path.join(OUTPUT_DIR, group['url']), 'w') as f:
            f.write(output_html)

    # Render index
    index_html = index_template.render(posts=index_posts, build_time=build_time)
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w') as f:
        f.write(index_html)
        
    print(f"Site built in {OUTPUT_DIR}/")

if __name__ == "__main__":
    build()
