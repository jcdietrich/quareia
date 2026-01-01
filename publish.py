import sys
import os
import shutil
import datetime
import argparse
import easyocr
# Importing build to trigger it automatically
import build

def process_image(image_path):
    print(f"Processing {image_path}...")
    
    if not os.path.exists(image_path):
        print(f"Error: File {image_path} not found.")
        return

    # 1. Setup paths
    filename = os.path.basename(image_path)
    base_name, ext = os.path.splitext(filename)
        today = datetime.date.today().isoformat()
        
        # Destination for image
        # Note: In build.py, we copy 'static' to 'docs/static'. 
        # So in the HTML, the path should be 'static/images/...'
        relative_img_dir = "static/images"
        dest_img_dir = os.path.join(os.getcwd(), relative_img_dir)    os.makedirs(dest_img_dir, exist_ok=True)
    
    # Unique image name to avoid collisions
    dest_image_name = f"{today}-{filename}"
    dest_image_path = os.path.join(dest_img_dir, dest_image_name)
    
    # Copy image
    shutil.copy2(image_path, dest_image_path)
    print(f"Image saved to {dest_image_path}")

    # 2. Perform OCR
    print("Initializing OCR engine (this might take a moment first time)...")
    # gpu=False to be safe on generic mac environment unless we are sure about mps/cuda
    # But easyocr handles mps on mac automatically in newer versions often. 
    # We'll stick to defaults which usually auto-detects or falls back to CPU.
    reader = easyocr.Reader(['en']) 
    
    print("Reading text from image...")
    result = reader.readtext(image_path, detail=0)
    transcribed_text = "\n\n".join(result)
    
    print("Transcription complete.")
    print("-" * 20)
    print(transcribed_text)
    print("-" * 20)

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
    # Since build.py copies 'static' to 'public/static', and public/index.html is root.
    # We need to be careful. 
    # In base.html/index.html we probably just use `static/images/...`?
    # Actually, in `build.py`: `shutil.copytree(STATIC_DIR, os.path.join(OUTPUT_DIR, 'static'))`
    # So `public/static/images/...` exists.
    # References in `public/index.html` should be `static/images/...`.
    img_url = f"static/images/{dest_image_name}"

    markdown_content = f"""
---
title: Note from {today}
date: {today}
image: {img_url}
---

### Transcription

{transcribed_text}

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
