import osmium
import argparse
import requests
import time
import os
import xml.etree.ElementTree as ET

CACHE_OBJECTS_FILE = "etymology_objects_cache.txt"
CACHE_CONTRIBUTORS_FILE = "etymology_contributors_cache.txt"

class EtymologyHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.objects = []

    def node(self, n):
        if 'name:etymology:wikidata' in n.tags:
            self.objects.append(('node', n.id))

    def way(self, w):
        if 'name:etymology:wikidata' in w.tags:
            self.objects.append(('way', w.id))

    def relation(self, r):
        if 'name:etymology:wikidata' in r.tags:
            self.objects.append(('relation', r.id))

def stage1_find_objects(pbf_file, use_cache=True):
    if use_cache and os.path.exists(CACHE_OBJECTS_FILE):
        print("Using cached objects file.")
        with open(CACHE_OBJECTS_FILE, "r", encoding="utf-8") as f:
            objects = [tuple(line.strip().split(',')) for line in f if line.strip()]
        return objects
    print("Scanning .pbf file for objects with name:etymology:wikidata...")
    handler = EtymologyHandler()
    handler.apply_file(pbf_file)
    with open(CACHE_OBJECTS_FILE, "w", encoding="utf-8") as f:
        for obj_type, obj_id in handler.objects:
            f.write(f"{obj_type},{obj_id}\n")
    return handler.objects

def stage2_fetch_contributors(objects, use_cache=True):
    contributors = set()
    already_done = set()
    already_done_count = 0
    if use_cache and os.path.exists(CACHE_CONTRIBUTORS_FILE):
        print("Using cached contributors file.")
        with open(CACHE_CONTRIBUTORS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) == 4:
                    already_done.add((parts[0], parts[1]))
                    contributors.add(tuple(parts))
        already_done_count = len(already_done)
    session = requests.Session()
    requests_made = already_done_count
    total_count = len(objects)
    for idx, (obj_type, obj_id) in enumerate(objects, 1):
        if (obj_type, obj_id) in already_done:
            continue
        if requests_made % 50 == 0 and requests_made > 0:
            print(f"Requesting history file {requests_made} out of {total_count}")
        url = f"https://api.openstreetmap.org/api/0.6/{obj_type}/{obj_id}/history"
        while True:
            try:
                resp = session.get(url)
                if resp.status_code == 429:
                    print("Rate limited, sleeping for 5 seconds...")
                    time.sleep(5)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                print(f"Error fetching {url}: {e}")
                time.sleep(5)
        requests_made += 1
        # if requests_made % 100 == 0:
        #     time.sleep(1)
        root = ET.fromstring(resp.content)
        seen_users = set()
        prev_tags = set()
        for elem in root.findall(obj_type):
            tags = {tag.attrib['k']: tag.attrib['v'] for tag in elem.findall('tag')}
            has_etymology = ('name:etymology:wikidata' in tags or 'name:etymology' in tags)
            had_etymology = ('name:etymology:wikidata' in prev_tags or 'name:etymology' in prev_tags)
            if has_etymology and not had_etymology:
                user = elem.attrib.get('user')
                uid = elem.attrib.get('uid')
                if user and uid and (user, uid) not in seen_users:
                    contributors.add((obj_type, obj_id, user, uid))
                    seen_users.add((user, uid))
            prev_tags = set(tags.keys())
        # Append new contributors to cache file
        with open(CACHE_CONTRIBUTORS_FILE, "a", encoding="utf-8") as f:
            for user, uid in seen_users:
                f.write(f"{obj_type},{obj_id},{user},{uid}\n")
    return contributors

def main():
    parser = argparse.ArgumentParser(description="Find OSM contributors for name:etymology:wikidata tags.")
    parser.add_argument("pbf_file", help="Input OSM .pbf file")
    parser.add_argument("--no-cache", action="store_true", help="Disable cache usage")
    args = parser.parse_args()
    use_cache = not args.no_cache

    objects = stage1_find_objects(args.pbf_file, use_cache=use_cache)
    contributors = stage2_fetch_contributors(objects, use_cache=use_cache)
    print(f"Found {len(contributors)} contributors.")
    # Optionally, print or process contributors here

if __name__ == "__main__":
    main()
