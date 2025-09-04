import os
import re
import requests
import argparse
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get_template_field(base_url, page_title, field_name):
    session = requests.Session()
    url = f"{base_url}/api.php"
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext",
        "format": "json"
    }
    
    print(f"\n--- DEBUG: Starting API request for page: '{page_title}' to find '{field_name}' (DIY parsing) ---")
    response = session.get(url, params=params)
    response.encoding = 'utf-8'
    
    try:
        data = response.json()
    except json.JSONDecodeError:
        print(f"ERROR: Could not decode JSON from API response for page '{page_title}'.")
        print(f"ERROR: Response status code: {response.status_code}")
        print(f"ERROR: Partial Response content (first 500 chars):\n{response.text[:500]}...")
        return None

    if "error" in data:
        print(f"ERROR: API returned an error for page '{page_title}': {data['error'].get('info', 'Unknown error')}")
        return None

    wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
    if not wikitext:
        print(f"⚠️ No wikitext found for page '{page_title}'.")
        return None

    # Step 1: Find the start of the 禁闭者图鉴 template
    template_start_match = re.search(r"{{\s*禁闭者图鉴", wikitext, re.DOTALL)
    if not template_start_match:
        print(f"⚠️ No 禁闭者图鉴 template start found on page '{page_title}'.")
        return None

    start_index = template_start_match.start()
    current_index = start_index
    brace_balance = 0
    template_text = ""
    
    # Simple state for comments to avoid parsing braces inside them
    in_comment = False 

    # Step 2 & 3: Iterate and count braces
    while current_index < len(wikitext):
        if wikitext[current_index:current_index+4] == '':
            in_comment = False
            current_index += 3
            continue

        if not in_comment:
            if wikitext[current_index:current_index+2] == '{{':
                brace_balance += 1
                template_text += '{{'
                current_index += 2
                continue
            elif wikitext[current_index:current_index+2] == '}}':
                brace_balance -= 1
                template_text += '}}'
                current_index += 2
                
                # Step 4: End condition
                if brace_balance == 0:
                    break # Found the closing brace for the main template
                continue
        
        # Add character to template text if not a brace or part of comment tag
        template_text += wikitext[current_index]
        current_index += 1
    else: # If loop finishes without balance reaching 0 (unbalanced braces)
        print(f"⚠️ Unbalanced braces or template not properly closed on page '{page_title}'.")
        return None

    # Debug print the extracted template (DIY method)
    print(f"\n--- DEBUG: Extracted '禁闭者图鉴' Template (DIY parsing) for '{page_title}' ---")
    print(template_text)
    print(f"--- END DEBUG: Extracted '禁闭者图鉴' Template ---")
    
    if "英文名" in template_text:
        print(f"DEBUG: The literal string '英文名' IS present in the extracted template text.")
    else:
        print(f"CRITICAL DEBUG: The literal string '英文名' is NOT present in the extracted template text (DIY).")

    # Step 5: Extract the specified parameter using regex (now that we have the full template text)
    # The regex for field extraction remains the same as it's designed to work within the template content.
    field_match = re.search(r"(?:\||\{\{)\s*" + re.escape(field_name) + r"\s*=\s*([^|\n\r}]+)", template_text)
    if field_match:
        value = field_match.group(1).strip()
        print(f"DEBUG: Successfully found field '{field_name}' with value: '{value}'.")
        return value
    else:
        print(f"⚠️ Field '{field_name}' not found inside 禁闭者图鉴 template on page '{page_title}' after DIY template extraction.")
        return None


def search_all_images(base_url, keyword):
    session = requests.Session()
    url = f"{base_url}/api.php"
    images = []
    params = {
        "action": "query",
        "list": "allimages",
        "ailimit": "max",
        "format": "json"
    }

    while True:
        response = session.get(url, params=params)
        response.encoding = 'utf-8'
        data = response.json()

        for image in data["query"]["allimages"]:
            if keyword in image["name"] and image["name"].endswith(".png"):
                images.append(image)

        if "continue" in data:
            params.update(data["continue"])
        else:
            break

    return images

def download_images_with_english_names(base_url, images, keyword, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    # --- NEW: Filter the images list BEFORE processing them ---
    print("Filtering image list to exclude unwanted files...")
    
    filtered_images = [img for img in images if "升阶装束" not in img["name"] and "" not in img["name"]]
    
    print(f"Found {len(images)} images initially. Will process {len(filtered_images)} after filtering.")
    
    for image in filtered_images:
        original_name = image["name"]
        
        # Calculate the base character name from the filename
        base_character_name = original_name.replace(keyword + ".png", "")
        
        # Construct the full wiki page title with the namespace
        character_page_title = f"禁闭者:{base_character_name}"
        
        print(f"\n--- Processing '{original_name}' ---")
        
        # Call the get_template_field function with the CORRECT page title
        english_name = get_template_field(base_url, character_page_title, "英文名")
        
        if not english_name:
            print(f"⚠️ Could not find 英文名 for '{character_page_title}'. Using original filename.")
            filename = original_name
        else:
            # --- START OF FILENAME SANITIZATION ---
            # 1. Convert to lowercase
            sanitized_name = english_name.lower()
            
            # 2. Remove all periods
            sanitized_name = sanitized_name.replace('.', '')
            
            # 3. Replace spaces and other invalid characters with underscores
            #    The regex replaces one or more of these characters with a single underscore.
            sanitized_name = re.sub(r'[\s\\/:"*?<>|]+', '_', sanitized_name)
            
            # Use the sanitized name for the new filename
            filename = sanitized_name + ".png"
            # --- END OF FILENAME SANITIZATION ---

        filepath = os.path.join(output_dir, filename)
        
        print(f"⬇ Downloading '{original_name}' as '{filename}'")
        try:
            response = requests.get(image["url"], timeout=30)
            with open(filepath, "wb") as f:
                f.write(response.content)
            print("✅ Download successful.")
        except requests.exceptions.RequestException as e:
            print(f"ERROR: A network error occurred while downloading '{original_name}': {e}")
 
            

def main():
    parser = argparse.ArgumentParser(description="Download MediaWiki images with English names from template field.")
    parser.add_argument("base_url", help="Base URL of the MediaWiki site, e.g. https://zh.example.org")
    parser.add_argument("keyword", help="Keyword in image filenames to filter, e.g. 证件照")
    parser.add_argument("--output", default="downloaded_images", help="Directory to save images")

    args = parser.parse_args()

    print(f"🔍 Searching images containing '{args.keyword}' from {args.base_url} ...")
    images = search_all_images(args.base_url, args.keyword)
    print(f"✅ Found {len(images)} image(s).")

    if images:
        download_images_with_english_names(args.base_url, images, args.keyword, args.output)
        print("🎉 All done!")
    else:
        print("⚠️ No matching images found.")

if __name__ == "__main__":
    main()