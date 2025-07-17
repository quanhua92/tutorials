# Spatial Indexing: Finding Your Place in the World 🗺️


* **`01-concepts-01-the-core-problem.md`**: How can a mapping application or a location-based game quickly find all points of interest within a specific geographic area (e.g., "all cafes within this visible map rectangle")?
* **`01-concepts-02-the-guiding-philosophy.md`**: Partition space hierarchically. Spatial indexes recursively divide a geographic area into smaller, manageable bounding boxes, creating a tree structure that allows for rapid elimination of irrelevant areas.
* **`01-concepts-03-key-abstractions.md`**: `Bounding box`, `Quadtree` (for 2D), and `Geohash`. Analogy: A set of nested maps. To find something in your neighborhood, you first open the world map, then a country map, then a city map, then your neighborhood map. You don't scan the entire world for a local cafe.
* **`02-guides-01-using-a-quadtree.md`**: A visual guide showing how a Quadtree recursively subdivides a 2D space as more points are added, and how a range query can efficiently select only the necessary quadrants.
* **`03-deep-dive-01-geohashing-for-proximity-searches.md`**: Explores the Geohash algorithm, which cleverly encodes 2D latitude/longitude coordinates into a single string. The beauty is that strings with a longer shared prefix represent points that are closer together, turning 2D proximity searches into simple 1D prefix searches.

---
