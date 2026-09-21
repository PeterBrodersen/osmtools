import osmium
import requests
import csv
import logging
import json
import os
import re
import time

osmFile = "denmark-latest.osm.pbf"
osmFile = "ostlandet-latest.osm.pbf"
# osmFile = 'andorra-latest.osm.pbf'

# Enable logging for debugging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


# Step 1: Fetch OSM objects with 'wikidata' key but without 'name:etymology:wikidata'
class OSMHandler(osmium.SimpleHandler):
    def __init__(self, max_elements=None):
        osmium.SimpleHandler.__init__(self)
        self.elements = []
        self.max_elements = max_elements
        self.reached_max = False

    def add_element(self, elem, elem_type):
        if self.max_elements is not None and len(self.elements) >= self.max_elements:
            self.reached_max = True
            return
        tags = elem.tags
        if "wikidata" in tags and "name:etymology:wikidata" not in tags:
            element = {"id": elem.id, "type": elem_type, "wikidata": tags["wikidata"]}
            if "name" in tags:
                element["name"] = tags["name"]
            self.elements.append(element)
            if len(self.elements) % 100 == 0:
                logging.info(f"Added {len(self.elements)} elements so far.")
            logging.debug(
                f"Added {elem_type} with ID {elem.id} and Wikidata ID {tags['wikidata']}"
            )

    def node(self, n):
        if not self.reached_max:
            self.add_element(n, "node")

    def way(self, w):
        if not self.reached_max:
            self.add_element(w, "way")

    def relation(self, r):
        if not self.reached_max:
            self.add_element(r, "relation")


def cache_result_to_file(result, filename):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f)


def read_cache_from_file(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def extract_wikidata_ids(value):
    """Return valid Wikidata item IDs from a tag, including semicolon lists."""
    return list(dict.fromkeys(re.findall(r"Q\d+", value or "")))


# User-Agent for Wikidata requests (set to identify your bot and include contact info if possible)
USER_AGENT = "FindvejEtymologyBot/1.0 (https://navne.findvej.dk/;peter@ter.dk)"

# Step 1: Read from cache or process OSM file
cache_file_step1 = "cache_osm_candidates.json"
cached_elements = read_cache_from_file(cache_file_step1)
max_elements = None  # Set the max limit for elements

if cached_elements:
    logging.info(f"Loaded {len(cached_elements)} elements from cache.")
    handler = OSMHandler(max_elements=max_elements)
    handler.elements = cached_elements
else:
    handler = OSMHandler(max_elements=max_elements)
    logging.info("Starting to apply OSM file...")
    handler.apply_file(osmFile)
    logging.info(f"Finished applying OSM file. Found {len(handler.elements)} elements.")
    cache_result_to_file(handler.elements, cache_file_step1)

# Step 2: Ask Wikidata for 'named after' (P138)
endpoint_url = "https://query.wikidata.org/sparql"
query_template = """
SELECT ?item ?namedAfter ?namedAfterLabel WHERE {{
  VALUES ?item {{ {wikidata_ids} }}
  OPTIONAL {{ ?item wdt:P138 ?namedAfter. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "da,en". }}
}}
"""

wikidata_results = {}
cache_file_step2 = "cache_wikidata_named_after.json"
cached_results = read_cache_from_file(cache_file_step2)

if cached_results:
    logging.info("Loaded results from cache.")
    wikidata_results = cached_results

# Filter out IDs already queried, and avoid sending malformed or duplicate IDs.
wikidata_ids_to_query = list(
    dict.fromkeys(
        wikidata_id
        for elem in handler.elements
        for wikidata_id in extract_wikidata_ids(elem.get("wikidata"))
        if wikidata_id not in wikidata_results
    )
)

batch_size = 50
for i in range(0, len(wikidata_ids_to_query), batch_size):
        batch = wikidata_ids_to_query[i : i + batch_size]
        wikidata_ids = " ".join(f"wd:{wikidata_id}" for wikidata_id in batch)
        query = query_template.format(wikidata_ids=wikidata_ids)
        if i % 1000 == 0:
            logging.info(f"Querying Wikidata for {i} items so far.")
        logging.debug(f"Querying Wikidata for batch {i // batch_size + 1}...")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
        data = None
        stop_querying = False
        for attempt in range(5):
            try:
                response = requests.get(
                    endpoint_url,
                    params={"query": query, "format": "json"},
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as e:
                logging.warning("Request error for batch %s (attempt %s/5): %s", i // batch_size + 1, attempt + 1, e)
                if attempt == 4:
                    break
                time.sleep(2 ** attempt)
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 120
                logging.warning("Wikidata rate limit for batch %s; retrying in %s seconds.", i // batch_size + 1, wait_seconds)
                if attempt == 4:
                    break
                time.sleep(wait_seconds)
                continue
            if response.status_code == 200:
                if response.content:
                    data = response.json()
                else:
                    logging.error("Empty response for batch %s", i // batch_size + 1)
                break
            if response.status_code == 403:
                logging.error(
                    "Error querying Wikidata: HTTP 403 - access forbidden. "
                    "Please set a proper User-Agent and respect the robot policy: https://w.wiki/4wJS"
                )
                stop_querying = True
                break

            logging.error("Error querying Wikidata: HTTP %s - %s", response.status_code, response.text)
            break

        if stop_querying:
            break
        if data is None:
            logging.error("Giving up on Wikidata batch %s; it will be retried next run.", i // batch_size + 1)
            continue

        for wikidata_id in batch:
            named_after_ids = set()
            named_after_labels = {}
            for result in data["results"]["bindings"]:
                if result["item"]["value"].endswith(wikidata_id):
                    if "namedAfter" in result:
                        named_after_url = result["namedAfter"]["value"]
                        named_after_id = named_after_url.split("/")[-1]
                        named_after_ids.add(named_after_id)
                        if "namedAfterLabel" in result:
                            named_after_labels[named_after_id] = result[
                                "namedAfterLabel"
                            ]["value"]
            if named_after_ids:
                wikidata_results[wikidata_id] = {
                    "ids": ";".join(named_after_ids),
                    "labels": ";".join(
                        named_after_labels[named_after_id]
                        for named_after_id in named_after_ids
                    ),
                }
                logging.debug(
                    f"Processed Wikidata ID {wikidata_id} with namedAfter IDs {wikidata_results[wikidata_id]['ids']} and labels {wikidata_results[wikidata_id]['labels']}"
                )
            else:
                wikidata_results[wikidata_id] = {"ids": "", "labels": ""}
        cache_result_to_file(wikidata_results, cache_file_step2)
        time.sleep(5)  # Keep request rate low for the public endpoint.

        if stop_querying:
            logging.info("Stopping further Wikidata queries due to HTTP 403 response.")
            break

# Step 3: Combine results and write output to CSV file
output_rows = [
    [
        "OSM_ID",
        "OSM_Type",
        "OSM_Link",
        "Wikidata_ID",
        "NamedAfter_ID",
        "NamedAfter_Label",
        "Name",
    ]
]
object_lines = []  # To store objects for objects.txt

for elem in handler.elements:
    wikidata_id = elem["wikidata"]
    element_ids = extract_wikidata_ids(wikidata_id)
    matching_results = [wikidata_results[item_id] for item_id in element_ids if item_id in wikidata_results]
    if matching_results:
        named_after_ids = ";".join(
            dict.fromkeys(
                item_id
                for result in matching_results
                for item_id in result["ids"].split(";")
                if item_id
            )
        )
        named_after_labels = ";".join(
            dict.fromkeys(
                label
                for result in matching_results
                for label in result["labels"].split(";")
                if label
            )
        )
        osm_link = f"https://www.openstreetmap.org/{elem['type']}/{elem['id']}"
        name = elem.get("name", "")
        output_rows.append(
            [
                elem["id"],
                elem["type"],
                osm_link,
                wikidata_id,
                named_after_ids,
                named_after_labels,
                name,
            ]
        )

        # Add object to the list for objects.txt
        object_prefix = {"node": "n", "way": "w", "relation": "r"}.get(elem["type"], "")
        if object_prefix:
            object_lines.append(f"{object_prefix}{elem['id']}")

# Write output to CSV file
with open("osm_etymology_data.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerows(output_rows)
logging.info("Finished writing output to osm_etymology_data.csv")

# Write objects to objects.txt
with open("objects.txt", "w", encoding="utf-8") as f:
    f.write(",".join(object_lines))
logging.info("Finished writing output to objects.txt")
