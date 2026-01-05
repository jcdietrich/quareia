#!venv/bin/python3
import os
import shutil
import markdown
import re
import argparse
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader

# Configuration
CONTENT_DIR = 'content/posts'
OUTPUT_DIR = 'docs'
TEMPLATE_DIR = 'templates'
STATIC_DIR = 'static'
LOOKUP_FILE = 'lesson_lookups.txt'

def load_lookups():
    lookups = {}
    if os.path.exists(LOOKUP_FILE):
        with open(LOOKUP_FILE, 'r') as f:
            for line in f:
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    lookups[parts[0]] = parts[1]
    return lookups

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-')

def parse_post(filepath, lookups=None):
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
                    val = value.strip()
                    if val.lower() == 'true':
                        val = True
                    elif val.lower() == 'false':
                        val = False
                    frontmatter[key.strip()] = val

    # Add <hr/> before second and subsequent timestamps and handle tags
    # Allow optional 'T' between date and time
    # Use stricter regex to avoid swallowing preceding text lines, but allow text on the SAME line (like NOTES [[...]])
    # Also support time formats like HHMM (4 digits) or HH:MM
    timestamp_pattern = r'((?:^|\n).*?\[\[\s*\d{4}[/ ]\d{2}[/ ]\d{2}[ T](?:\d{2}:\d{2}:\d{2}|\d{2}:\d{2}|\d{4}) \(?[A-Z]{3}\)?\s*\]\])'
    parts = re.split(timestamp_pattern, body)
    
    found_tags = []
    
    def process_tags(text, extract=False):
        extracted_html = ""
        def replace_tag_match(match):
            nonlocal extracted_html
            raw_tags = match.group(1)
            tags_list = [t.strip() for t in raw_tags.split(',')]
            
            html_list = "<ul>"
            for tag in tags_list:
                slug = slugify(tag)
                found_tags.append({'name': tag, 'slug': slug})
                html_list += f'<li><a href="tag_{slug}.html">{tag}</a></li>'
            html_list += "</ul>"
            
            if extract:
                extracted_html += html_list
                return ""
            else:
                return html_list

        new_text = re.sub(r'<<\s*(.*?)\s*>>', replace_tag_match, text)
        return new_text, extracted_html

    if len(parts) == 1:
        # No timestamps found, process tags in-place
        body, _ = process_tags(body, extract=False)
    else:
        new_body_parts = []
        
        # Preamble (before first timestamp) - process tags in-place
        preamble, _ = process_tags(parts[0], extract=False)
        new_body_parts.append(preamble)
        
        # Iterate over timestamp+content pairs
        num_entries = (len(parts) - 1) // 2
        for i in range(num_entries):
            idx = 1 + i*2
            ts_raw = parts[idx].strip()
            entry_content = parts[idx+1]
            
            # Split into Title and Timestamp if title exists
            header_split_match = re.match(r'^(.*?)(\[\[.*?\]\])$', ts_raw, re.DOTALL)
            if header_split_match:
                title_part = header_split_match.group(1).strip()
                ts_part = header_split_match.group(2).strip()
                if title_part:
                    ts = f"{title_part}<br/>{ts_part}"
                else:
                    ts = ts_part
            else:
                ts = ts_raw
            
            # Check if timestamp is in the future
            ts_match = re.search(r'\[\[\s*(\d{4}[/ ]\d{2}[/ ]\d{2})', ts)
            is_future_ts = False
            if ts_match:
                ts_date_str = ts_match.group(1).replace('/', '-').replace(' ', '-')
                ts_date = datetime.strptime(ts_date_str, "%Y-%m-%d").date()
            
            classes = ["timestamp-header"]
            if is_future_ts:
                classes.append("future-warning")
            
            ts = f'<h3 class="{" ".join(classes)}">{ts}</h3>'

            # Process tags in content, replacing them in-place
            cleaned_content, _ = process_tags(entry_content, extract=False)
            
            # Construct entry block: Timestamp + Content (with in-place tags)
            # Ensure proper spacing
            entry_block = f"{ts}\n\n{cleaned_content.lstrip()}"
            
            # Add separator if not the first entry
            if i > 0:
                new_body_parts.append("\n\n---\n\n")
            elif parts[0].strip():
                 # If there was preamble text, we might want a separator or just newline?
                 # Standard behavior was just concat.
                 pass

            new_body_parts.append(entry_block)
            
        body = "".join(new_body_parts)

    # Process bullet point links

    # Process bullet point links
    if lookups:
        # Match bullet points starting with 'module' (case insensitive) and ending with a number
        pattern = re.compile(r'^(\s*[-*+]\s+)([Mm]odule\b.*?(\d+(?:\.\d+)?))\s*$', re.MULTILINE)
        def replace_link(match):
            prefix = match.group(1)
            content = match.group(2)
            number = match.group(3)
            if number in lookups:
                return f"{prefix}[{content}]({lookups[number]})"
            print(f"Warning: No lookup found for module {number} in {filepath}")
            return match.group(0)
        body = pattern.sub(replace_link, body)

    # Ensure empty line after bullet points if followed by text
    # This prevents the next line from being swallowed into the list item
    body = re.sub(r'(^(\s*[-*+]\s+|\s{2,}).*)\n(?=[^ \t\n\-\*\]])', r'\1\n\n', body, flags=re.MULTILINE)

    # Start a new list if bullet indicator changes (*, -, +)
    def bullet_breaker(match):
        b1 = match.group(2).strip()
        b2 = match.group(4).strip()
        if b1 != b2:
            return match.group(1) + "\n\n"
        return match.group(1) + "\n"

    body = re.sub(r'(^(\s*[-*+])\s+.*)\n(?=(\s*([-*+])\s+.*))', bullet_breaker, body, flags=re.MULTILINE)

    # Wrap Astro data list in a div for specific styling
    def wrap_astro_data(text):
        # Regex to find a block of list items
        # Matches continuous lines starting with a bullet
        list_block_pattern = re.compile(r'((?:^[ \t]*[*•-].*?(?:\n|$))+)', re.MULTILINE)
        
        def check_and_wrap(match):
            block = match.group(1)
            # Check for Astro keywords
            if re.search(r'(Location:|Sunrise:|Moon phase:)', block):
                return f'<div class="astro-data" markdown="1">\n\n{block}\n</div>\n'
            return block

        return list_block_pattern.sub(check_and_wrap, text)

    body = wrap_astro_data(body)

    # Extract first timestamp for sorting
    ts_match = re.search(r'\[\[\s*(\d{4}[/ ]\d{2}[/ ]\d{2}[ T]\d{2}:\d{2}:\d{2})', body)
    sort_key = ts_match.group(1) if ts_match else "9999/99/99 99:99:99"
    # Normalize sort key to have slashes and single space
    if ts_match:
        sort_key = sort_key.replace(' ', '/').replace('T', '/') # Normalize all to same separator for string sort
        # Wait, if I replace space with slash it becomes YYYY/MM/DD/HH:MM:SS
        # This works for sorting.

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
        'url': filename.replace('.md', '.html'),
        'tags': found_tags,
        'sort_key': sort_key,
        'raw_content': content
    }

def write_if_changed(path, content, force=False):
    """
    Writes content to path only if it differs from existing content (ignoring timestamp).
    Returns True if written, False otherwise.
    """
    should_write = True
    if not force and os.path.exists(path):
        with open(path, 'r') as f:
            current_content = f.read()
        
        # Normalize: Remove the dynamic timestamp for comparison (support EST and UTC)
        time_pattern = r'updated last: \d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (EST|UTC)'
        
        norm_new = re.sub(time_pattern, '', content)
        norm_old = re.sub(time_pattern, '', current_content)
        
        if norm_new == norm_old:
            should_write = False

    if should_write:
        with open(path, 'w') as f:
            f.write(content)
        print(f"Built {os.path.basename(path)}")
    
    return should_write

def build(force=False):
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
    tags_template = env.get_template('tags.html')
    tag_page_template = env.get_template('tag_page.html')

    # Check global dependencies (templates + build script)
    global_mtime = os.stat(__file__).st_mtime
    for t_name in env.list_templates():
        t_path = os.path.join(TEMPLATE_DIR, t_name)
        if os.path.exists(t_path):
            global_mtime = max(global_mtime, os.stat(t_path).st_mtime)

    posts_by_date = {}
    all_tags = {}  # { 'slug': { 'name': 'Name', 'posts': [] } }
    
    build_time = datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M:%S UTC')
    lookups = load_lookups()
    
    # Add lookup file to global_mtime
    if os.path.exists(LOOKUP_FILE):
        global_mtime = max(global_mtime, os.stat(LOOKUP_FILE).st_mtime)

    if os.path.exists(CONTENT_DIR):
        files = [f for f in os.listdir(CONTENT_DIR) if f.endswith('.md')]
        
        for file in files:
            filepath = os.path.join(CONTENT_DIR, file)
            # Optimization: We could read frontmatter only first, but files are small.
            post = parse_post(filepath, lookups=lookups)
            date = post['metadata'].get('date')
            
            # Aggregate tags
            daily_url = f"{date}.html"
            for tag in post['tags']:
                if tag['slug'] not in all_tags:
                    all_tags[tag['slug']] = {'name': tag['name'], 'slug': tag['slug'], 'posts': []}
                
                # Avoid duplicates per post if same tag appears multiple times
                if not any(p['url'] == daily_url for p in all_tags[tag['slug']]['posts']):
                    all_tags[tag['slug']]['posts'].append({
                        'title': post['metadata'].get('title'),
                        'date': date,
                        'url': daily_url
                    })

            if date not in posts_by_date:
                posts_by_date[date] = {
                    'title': date,
                    'date': date,
                    'entries': [],
                    'url': f"{date}.html",
                    'max_mtime': 0,
                    'has_future': False
                }
            
            # Update max_mtime for this date group
            file_mtime = os.stat(filepath).st_mtime
            posts_by_date[date]['max_mtime'] = max(posts_by_date[date]['max_mtime'], file_mtime)

            is_tech = file.endswith('-tech.md')
            is_future = post['metadata'].get('future', False)
            
            if is_future:
                posts_by_date[date]['has_future'] = True
            
            posts_by_date[date]['entries'].append({
                'content': post['content'],
                'image': post['metadata'].get('image'),
                'sort_key': post['sort_key'],
                'is_tech': is_tech,
                'is_future': is_future,
                'filename': file,
                'raw_content': post['raw_content']
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
            'image': first_image,
            'is_future': group['has_future']
        })
        
        # Incremental check
        needs_rebuild = True
        if not force and os.path.exists(output_path):
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
                has_future=group['has_future'],
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
    
    write_if_changed(index_path, index_html, force)
    generated_files.add('index.html')

    # Generate Tags Index
    tags_list = sorted(all_tags.values(), key=lambda x: x['name'].lower())
    tags_html = tags_template.render(tags=tags_list, build_time=build_time)
    tags_path = os.path.join(OUTPUT_DIR, 'tags.html')
    
    write_if_changed(tags_path, tags_html, force)
    generated_files.add('tags.html')

    # Generate Individual Tag Pages
    for slug, data in all_tags.items():
        tag_filename = f"tag_{slug}.html"
        tag_path = os.path.join(OUTPUT_DIR, tag_filename)
        # Sort posts by date descending
        sorted_posts = sorted(data['posts'], key=lambda x: x['date'], reverse=True)
        
        tag_page_html = tag_page_template.render(
            tag_name=data['name'],
            posts=sorted_posts,
            build_time=build_time
        )
        
        write_if_changed(tag_path, tag_page_html, force)
        generated_files.add(tag_filename)

    # Cleanup stale files
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith('.html') and f not in generated_files:
            print(f"Removing stale file: {f}")
            os.remove(os.path.join(OUTPUT_DIR, f))
        
    print(f"Site built in {OUTPUT_DIR}/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build the site.')
    parser.add_argument('-f', '--force', action='store_true', help='Force rebuild of all pages')
    args = parser.parse_args()
    build(force=args.force)