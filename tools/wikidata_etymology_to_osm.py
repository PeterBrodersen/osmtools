import osmium
import requests
import csv
import logging

# Enable logging for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Trin 1: Udtræk OSM-objekter med 'wikidata'-nøglen, men uden 'name:etymology:wikidata'
class OSMHandler(osmium.SimpleHandler):
    def __init__(self):
        osmium.SimpleHandler.__init__(self)
        self.elements = []

    def add_element(self, elem, elem_type):
        tags = elem.tags
        if 'wikidata' in tags and 'name:etymology:wikidata' not in tags:
            self.elements.append({
                'id': elem.id,
                'type': elem_type,
                'wikidata': tags['wikidata']
            })
            logging.debug(f"Added {elem_type} with ID {elem.id} and Wikidata ID {tags['wikidata']}")

    def node(self, n):
        self.add_element(n, 'node')

    def way(self, w):
        self.add_element(w, 'way')

    def relation(self, r):
        self.add_element(r, 'relation')

# Indlæs OSM-data
handler = OSMHandler()
logging.info("Starting to apply OSM file...")
handler.apply_file('denmark.osm.pbf')
logging.info(f"Finished applying OSM file. Found {len(handler.elements)} elements.")

# Trin 2 og 3: Forespørg Wikidata for 'opkaldt efter' (P138) og opret output
endpoint_url = "https://query.wikidata.org/sparql"
query_template = """
SELECT ?item ?namedAfter WHERE {{
  VALUES ?item {{ wd:{wikidata_id} }}
  OPTIONAL {{ ?item wdt:P138 ?namedAfter. }}
}}
"""

output_rows = [['OSM_ID', 'OSM_Type', 'OSM_Link', 'Wikidata_ID', 'NamedAfter_ID']]

for elem in handler.elements:
    wikidata_id = elem['wikidata']
    query = query_template.format(wikidata_id=wikidata_id)
    logging.debug(f"Querying Wikidata for ID {wikidata_id}...")
    response = requests.get(endpoint_url, params={'query': query, 'format': 'json'})
    data = response.json()
    named_after_id = None
    if data['results']['bindings']:
        result = data['results']['bindings'][0]
        if 'namedAfter' in result:
            named_after_url = result['namedAfter']['value']
            named_after_id = named_after_url.split('/')[-1]
    osm_link = f"https://www.openstreetmap.org/{elem['type']}/{elem['id']}"
    output_rows.append([elem['id'], elem['type'], osm_link, wikidata_id, named_after_id])
    logging.debug(f"Processed element {elem['id']} with namedAfter ID {named_after_id}")

# Skriv output til CSV-fil
with open('osm_etymology_data.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerows(output_rows)
logging.info("Finished writing output to osm_etymology_data.csv")
