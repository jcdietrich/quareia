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
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    # Sync static assets (only if newer)
    if os.path.exists(STATIC_DIR):
        dest_static = os.path.join(OUTPUT_DIR, 'static')
        if not os.path.exists(dest_static):
            os.makedirs(dest_static)
        for root, dirs, files in os.walk(STATIC_DIR):
            rel_path = os.path.relpath(root, STATIC_DIR)
            dest_root = os.path.join(dest_static, rel_path)
            if not os.path.exists(dest_root):
                os.makedirs(dest_root)
            for file in files:
                src_file = os.path.join(root, file)
                dest_file = os.path.join(dest_root, file)
                if not os.path.exists(dest_file) or os.stat(src_file).st_mtime > os.stat(dest_file).st_mtime:
                    shutil.copy2(src_file, dest_file)

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    post_template = env.get_template('post.html')
    index_template = env.get_template('index.html')

    # Check global dependencies (templates + build script)
    global_mtime = os.stat(__file__).st_mtime
    for t_name in env.list_templates():
        t_path = os.path.join(TEMPLATE_DIR, t_name)
        if os.path.exists(t_path):
            global_mtime = max(global_mtime, os.stat(t_path).st_mtime)

    posts_by_date = {}
    build_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S EST')
    
    if os.path.exists(CONTENT_DIR):
        files = [f for f in os.listdir(CONTENT_DIR) if f.endswith('.md')]
        
        for file in files:
            filepath = os.path.join(CONTENT_DIR, file)
            # Optimization: We could read frontmatter only first, but files are small.
            post = parse_post(filepath)
            date = post['metadata'].get('date')
            
            if date not in posts_by_date:
                posts_by_date[date] = {
                    'title': date,
                    'date': date,
                    'entries': [],
                    'url': f"{date}.html",
                    'max_mtime': 0
                }
            
            # Update max_mtime for this date group
            file_mtime = os.stat(filepath).st_mtime
            posts_by_date[date]['max_mtime'] = max(posts_by_date[date]['max_mtime'], file_mtime)

            # Determine sort key
            with open(filepath, 'r') as f:
                raw_content = f.read()
            
            ts_match = re.search(r'\[\[(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', raw_content)
            if ts_match:
                sort_key = ts_match.group(1)
            else:
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
    
    generated_files = set()

    for date in sorted_dates:
        group = posts_by_date[date]
        output_path = os.path.join(OUTPUT_DIR, group['url'])
        generated_files.add(group['url'])
        
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
        
        # Incremental check
        needs_rebuild = True
        if os.path.exists(output_path):
            output_mtime = os.stat(output_path).st_mtime
            # If output is newer than both global deps and source content -> skip
            if output_mtime > global_mtime and output_mtime > group['max_mtime']:
                needs_rebuild = False
        
        if needs_rebuild:
            # Render daily page
            output_html = post_template.render(
                title=group['title'],
                date=group['date'],
                entries=group['entries'],
                build_time=build_time
            )
            
            with open(output_path, 'w') as f:
                f.write(output_html)
            print(f"Built {group['url']}")
        else:
            # print(f"Skipped {group['url']} (up to date)")
            pass

    # Render index (Conditionally write if content changed)
    index_html = index_template.render(posts=index_posts, build_time=build_time)
    index_path = os.path.join(OUTPUT_DIR, 'index.html')
    
    write_index = True
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            current_index_html = f.read()
        
        # Normalize: Remove the dynamic timestamp for comparison
        # Pattern: updated last: YYYY/MM/DD HH:MM:SS EST
        # We can be aggressive or specific. Specific is safer.
        # The build_time format is '%Y/%m/%d %H:%M:%S EST'
        # Regex: updated last: \d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} EST
        
        time_pattern = r'updated last: \d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} EST'
        
        norm_new = re.sub(time_pattern, '', index_html)
        norm_old = re.sub(time_pattern, '', current_index_html)
        
        if norm_new == norm_old:
            write_index = False
            # print("Skipped index.html (content up to date)")

    if write_index:
        with open(index_path, 'w') as f:
            f.write(index_html)
        print("Built index.html")
        
    generated_files.add('index.html')

    # Cleanup stale files
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith('.html') and f not in generated_files:
            print(f"Removing stale file: {f}")
            os.remove(os.path.join(OUTPUT_DIR, f))
        
    print(f"Site built in {OUTPUT_DIR}/")

if __name__ == "__main__":
    build()
