# overpass_fetcher.py
# Fetches traffic signal junction coordinates from Overpass API (OpenStreetMap)
# for a given bounding box in Bengaluru and returns structured junction data.

def fetch_junctions(bbox: tuple) -> list[dict]:
    """
    Query Overpass API for highway=traffic_signals nodes within bbox.
    bbox: (min_lat, min_lon, max_lat, max_lon)
    Returns: list of { osm_node_id, lat, lng, name }
    """
    pass
