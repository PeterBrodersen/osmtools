import osmium
import psycopg2
import sys
import os
import argparse

class TagUpdaterHandler(osmium.SimpleHandler):
    def __init__(self, node_ids, way_ids, key, value):
        super().__init__()
        self.node_ids = set(node_ids)
        self.way_ids = set(way_ids)
        self.key = key
        self.value = value
        self.updated_nodes = {}  # id -> tags
        self.updated_ways = {}   # id -> tags

    def node(self, n):
        if n.id in self.node_ids:
            tags = dict(n.tags)
            tags[self.key] = self.value
            self.updated_nodes[n.id] = tags

    def way(self, w):
        if w.id in self.way_ids:
            tags = dict(w.tags)
            tags[self.key] = self.value
            self.updated_ways[w.id] = tags

# Dummy function to get node and way IDs from Postgres
def get_osm_ids_from_db(conn, param1, param2):
    queries = [
        ("'point'", "node_ids"),
        ("'line','polygon'", "way_ids")
    ]
    results = {"node_ids": [], "way_ids": []}

    with conn.cursor() as cur:
        for geomtype, key in queries:
            cur.execute(f"""
                SELECT UNNEST(l.object_ids) AS unnested_ids
                FROM osmetymology.locations_agg l
                INNER JOIN osmetymology.wikidata w ON l.wikidatas @> ARRAY[w.itemid]
                WHERE w.claims @@ '$.P21[*].mainsnak.datavalue.value.id == "Q6581097"'
                AND l.geomtype IN({geomtype})
            """)
            results[key].extend(int(row[0]) for row in cur.fetchall() if row[0])

    print(f"Found {len(results['node_ids'])} nodes and {len(results['way_ids'])} ways")
    return results["node_ids"], results["way_ids"]

# Function to update OSM file with key/value for given node and way IDs
def update_osm_tags(input_file, node_ids, way_ids, key, value, output_file):
    handler = TagUpdaterHandler(node_ids, way_ids, key, value)
    handler.apply_file(input_file)
    print(f"Nodes to update: {len(handler.updated_nodes)}; Ways to update: {len(handler.updated_ways)}")

    import osmium as o
    writer = o.SimpleWriter(output_file, o.osm.osm_entity_bits.ALL)

    class CopyHandler(o.SimpleHandler):
        def __init__(self, updated_nodes, updated_ways):
            super().__init__()
            self.updated_nodes = updated_nodes  # id -> tags
            self.updated_ways = updated_ways    # id -> tags
        def node(self, n):
            if n.id in self.updated_nodes:
                mnode = o.osm.mutable.Node(n)
                mnode.tags = [(k, v) for k, v in self.updated_nodes[n.id].items()]
                writer.add_node(mnode)
            else:
                writer.add_node(n)
        def way(self, w):
            if w.id in self.updated_ways:
                mway = o.osm.mutable.Way(w)
                mway.tags = [(k, v) for k, v in self.updated_ways[w.id].items()]
                writer.add_way(mway)
            else:
                writer.add_way(w)
        def relation(self, r):
            writer.add_relation(r)
    copy_handler = CopyHandler(handler.updated_nodes, handler.updated_ways)
    copy_handler.apply_file(input_file)
    writer.close()
    print(f"Wrote updated data to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update OSM tags for selected node and way IDs.")
    parser.add_argument("input_file", nargs="?", help="Input OSM or PBF file")
    parser.add_argument("output_file", nargs="?", help="Output OSM or PBF file")
    args = parser.parse_args()

    if not args.input_file or not args.output_file:
        print("Usage: python osm_add_tags.py <input_file> <output_file>")
        sys.exit(1)

    input_file = args.input_file
    output_file = args.output_file

    # Read DB params from environment
    db_params = {
        'dbname': os.environ.get('PGDATABASE'),
        'user': os.environ.get('PGUSER'),
        'password': os.environ.get('PGPASSWORD'),
        'host': os.environ.get('PGHOST', 'localhost'),
        'port': int(os.environ.get('PGPORT', 5432)),
    }
    missing = [k for k in ['dbname', 'user', 'password'] if not db_params[k]]
    if missing:
        print(f"Missing required environment variables: {', '.join(['PGDATABASE' if k=='dbname' else 'PGUSER' if k=='user' else 'PGPASSWORD' for k in missing])}")
        sys.exit(1)

    conn = psycopg2.connect(**db_params)
    node_ids, way_ids = get_osm_ids_from_db(conn, 'foo', 'bar')
    update_osm_tags(input_file, node_ids, way_ids, 'etymology_has_male', 'yes', output_file)
    conn.close()
