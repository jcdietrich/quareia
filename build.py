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

    html_content = markdown.markdown(body, extensions=['extra'])
    
    # Infer date/title if missing
    filename = os.path.basename(filepath)
    if 'title' not in frontmatter:
        frontmatter['title'] = os.path.splitext(filename)[0].replace('-', ' ').title()
    if 'date' not in frontmatter:
        # Try to parse from filename YYYY-MM-DD
        match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
        if match:
            frontmatter['date'] = match.group(1)
        else:
            frontmatter['date'] = datetime.now().strftime('%Y-%m-%d')
            
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

    posts = []
    
    # Process posts
    build_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S EST')
    
    if os.path.exists(CONTENT_DIR):
        files = [f for f in os.listdir(CONTENT_DIR) if f.endswith('.md')]
        files.sort(reverse=True) # Simple sort by filename (usually date) 
        
        for file in files:
            filepath = os.path.join(CONTENT_DIR, file)
            post = parse_post(filepath)
            posts.append({
                'title': post['metadata'].get('title'),
                'date': post['metadata'].get('date'),
                'url': post['url'],
                'image': post['metadata'].get('image', ''),
                'raw_date': post['metadata'].get('date') # For sorting if needed
            })
            
            # Render post
            output_html = post_template.render(
                title=post['metadata'].get('title'),
                date=post['metadata'].get('date'),
                image=post['metadata'].get('image'),
                content=post['content'],
                build_time=build_time
            )
            
            with open(os.path.join(OUTPUT_DIR, post['url']), 'w') as f:
                f.write(output_html)

    # Render index
    index_html = index_template.render(posts=posts, build_time=build_time)
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w') as f:
        f.write(index_html)
        
    print(f"Site built in {OUTPUT_DIR}/")

if __name__ == "__main__":
    build()
