# Rust Implementation: High-Performance Spatial Indexing

This implementation provides efficient, memory-safe spatial indexing structures in Rust, focusing on performance, correctness, and real-world usability.

## Project Setup

Create a new Rust project:

```bash
cargo new spatial_indexing
cd spatial_indexing
```

Add dependencies to `Cargo.toml`:

```toml
[package]
name = "spatial_indexing"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
rand = "0.8"
criterion = { version = "0.5", optional = true }

[dev-dependencies]
criterion = "0.5"

[[bench]]
name = "spatial_benchmark"
harness = false

[features]
default = []
benchmarks = ["criterion"]
```

## Core Spatial Types and Traits

```rust
// src/types.rs
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

impl Point {
    pub fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }
    
    pub fn distance_to(&self, other: &Point) -> f64 {
        ((self.x - other.x).powi(2) + (self.y - other.y).powi(2)).sqrt()
    }
    
    pub fn manhattan_distance_to(&self, other: &Point) -> f64 {
        (self.x - other.x).abs() + (self.y - other.y).abs()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Rectangle {
    pub min_x: f64,
    pub min_y: f64,
    pub max_x: f64,
    pub max_y: f64,
}

impl Rectangle {
    pub fn new(min_x: f64, min_y: f64, max_x: f64, max_y: f64) -> Self {
        assert!(min_x <= max_x && min_y <= max_y);
        Self { min_x, min_y, max_x, max_y }
    }
    
    pub fn from_points(points: &[Point]) -> Option<Self> {
        if points.is_empty() {
            return None;
        }
        
        let mut min_x = points[0].x;
        let mut max_x = points[0].x;
        let mut min_y = points[0].y;
        let mut max_y = points[0].y;
        
        for point in points.iter().skip(1) {
            min_x = min_x.min(point.x);
            max_x = max_x.max(point.x);
            min_y = min_y.min(point.y);
            max_y = max_y.max(point.y);
        }
        
        Some(Self::new(min_x, min_y, max_x, max_y))
    }
    
    pub fn contains_point(&self, point: &Point) -> bool {
        point.x >= self.min_x && point.x <= self.max_x &&
        point.y >= self.min_y && point.y <= self.max_y
    }
    
    pub fn intersects(&self, other: &Rectangle) -> bool {
        !(self.max_x < other.min_x || other.max_x < self.min_x ||
          self.max_y < other.min_y || other.max_y < self.min_y)
    }
    
    pub fn union(&self, other: &Rectangle) -> Rectangle {
        Rectangle::new(
            self.min_x.min(other.min_x),
            self.min_y.min(other.min_y),
            self.max_x.max(other.max_x),
            self.max_y.max(other.max_y),
        )
    }
    
    pub fn area(&self) -> f64 {
        (self.max_x - self.min_x) * (self.max_y - self.min_y)
    }
    
    pub fn center(&self) -> Point {
        Point::new(
            (self.min_x + self.max_x) / 2.0,
            (self.min_y + self.max_y) / 2.0,
        )
    }
    
    pub fn min_distance_to_point(&self, point: &Point) -> f64 {
        let dx = (self.min_x - point.x).max(0.0).max(point.x - self.max_x);
        let dy = (self.min_y - point.y).max(0.0).max(point.y - self.max_y);
        (dx * dx + dy * dy).sqrt()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpatialObject<T> {
    pub point: Point,
    pub data: T,
}

impl<T> SpatialObject<T> {
    pub fn new(point: Point, data: T) -> Self {
        Self { point, data }
    }
}

pub trait SpatialIndex<T> {
    fn insert(&mut self, object: SpatialObject<T>);
    fn query_range(&self, range: &Rectangle) -> Vec<&SpatialObject<T>>;
    fn query_nearest(&self, point: &Point, k: usize) -> Vec<&SpatialObject<T>>;
    fn query_within_distance(&self, point: &Point, distance: f64) -> Vec<&SpatialObject<T>>;
    fn size(&self) -> usize;
}
```

## QuadTree Implementation

```rust
// src/quadtree.rs
use crate::types::{Point, Rectangle, SpatialObject, SpatialIndex};
use std::collections::BinaryHeap;
use std::cmp::Ordering;

pub struct QuadTree<T> {
    root: QuadTreeNode<T>,
    capacity: usize,
    size: usize,
}

enum QuadTreeNode<T> {
    Leaf {
        boundary: Rectangle,
        objects: Vec<SpatialObject<T>>,
    },
    Internal {
        boundary: Rectangle,
        children: Box<[QuadTreeNode<T>; 4]>,
    },
}

impl<T> QuadTree<T> {
    pub fn new(boundary: Rectangle, capacity: usize) -> Self {
        Self {
            root: QuadTreeNode::Leaf {
                boundary,
                objects: Vec::new(),
            },
            capacity,
            size: 0,
        }
    }
    
    pub fn clear(&mut self) {
        let boundary = self.root.boundary();
        self.root = QuadTreeNode::Leaf {
            boundary,
            objects: Vec::new(),
        };
        self.size = 0;
    }
}

impl<T> QuadTreeNode<T> {
    fn boundary(&self) -> Rectangle {
        match self {
            QuadTreeNode::Leaf { boundary, .. } => *boundary,
            QuadTreeNode::Internal { boundary, .. } => *boundary,
        }
    }
    
    fn insert(&mut self, object: SpatialObject<T>, capacity: usize) -> bool {
        let boundary = self.boundary();
        
        if !boundary.contains_point(&object.point) {
            return false;
        }
        
        match self {
            QuadTreeNode::Leaf { objects, .. } => {
                objects.push(object);
                
                // Subdivide if over capacity
                if objects.len() > capacity {
                    self.subdivide(capacity);
                }
                true
            }
            QuadTreeNode::Internal { children, .. } => {
                children[0].insert(object.clone(), capacity) ||
                children[1].insert(object.clone(), capacity) ||
                children[2].insert(object.clone(), capacity) ||
                children[3].insert(object, capacity)
            }
        }
    }
    
    fn subdivide(&mut self, capacity: usize) {
        if let QuadTreeNode::Leaf { boundary, objects } = self {
            let center = boundary.center();
            
            let nw = Rectangle::new(boundary.min_x, center.y, center.x, boundary.max_y);
            let ne = Rectangle::new(center.x, center.y, boundary.max_x, boundary.max_y);
            let sw = Rectangle::new(boundary.min_x, boundary.min_y, center.x, center.y);
            let se = Rectangle::new(center.x, boundary.min_y, boundary.max_x, center.y);
            
            let mut children = Box::new([
                QuadTreeNode::Leaf { boundary: nw, objects: Vec::new() },
                QuadTreeNode::Leaf { boundary: ne, objects: Vec::new() },
                QuadTreeNode::Leaf { boundary: sw, objects: Vec::new() },
                QuadTreeNode::Leaf { boundary: se, objects: Vec::new() },
            ]);
            
            // Redistribute objects to children
            for object in objects.drain(..) {
                let inserted = 
                    children[0].insert(object.clone(), capacity) ||
                    children[1].insert(object.clone(), capacity) ||
                    children[2].insert(object.clone(), capacity) ||
                    children[3].insert(object, capacity);
                
                debug_assert!(inserted);
            }
            
            *self = QuadTreeNode::Internal {
                boundary: *boundary,
                children,
            };
        }
    }
    
    fn query_range<'a>(&'a self, range: &Rectangle, results: &mut Vec<&'a SpatialObject<T>>) {
        let boundary = self.boundary();
        
        if !boundary.intersects(range) {
            return;
        }
        
        match self {
            QuadTreeNode::Leaf { objects, .. } => {
                for object in objects {
                    if range.contains_point(&object.point) {
                        results.push(object);
                    }
                }
            }
            QuadTreeNode::Internal { children, .. } => {
                for child in children.iter() {
                    child.query_range(range, results);
                }
            }
        }
    }
    
    fn query_nearest<'a>(
        &'a self,
        point: &Point,
        heap: &mut BinaryHeap<DistanceEntry<'a, T>>,
        k: usize,
    ) {
        let boundary = self.boundary();
        let min_distance = boundary.min_distance_to_point(point);
        
        // Prune if this node can't contain closer points
        if heap.len() >= k {
            if let Some(furthest) = heap.peek() {
                if min_distance >= furthest.distance {
                    return;
                }
            }
        }
        
        match self {
            QuadTreeNode::Leaf { objects, .. } => {
                for object in objects {
                    let distance = point.distance_to(&object.point);
                    
                    if heap.len() < k {
                        heap.push(DistanceEntry { object, distance });
                    } else if let Some(mut furthest) = heap.peek_mut() {
                        if distance < furthest.distance {
                            furthest.object = object;
                            furthest.distance = distance;
                        }
                    }
                }
            }
            QuadTreeNode::Internal { children, .. } => {
                // Sort children by distance to query point for better pruning
                let mut child_distances: Vec<_> = children
                    .iter()
                    .map(|child| {
                        let distance = child.boundary().min_distance_to_point(point);
                        (child, distance)
                    })
                    .collect();
                
                child_distances.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(Ordering::Equal));
                
                for (child, _) in child_distances {
                    child.query_nearest(point, heap, k);
                }
            }
        }
    }
}

#[derive(Debug)]
struct DistanceEntry<'a, T> {
    object: &'a SpatialObject<T>,
    distance: f64,
}

impl<'a, T> PartialEq for DistanceEntry<'a, T> {
    fn eq(&self, other: &Self) -> bool {
        self.distance == other.distance
    }
}

impl<'a, T> Eq for DistanceEntry<'a, T> {}

impl<'a, T> PartialOrd for DistanceEntry<'a, T> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        // Reverse ordering for max-heap behavior (we want min-heap)
        other.distance.partial_cmp(&self.distance)
    }
}

impl<'a, T> Ord for DistanceEntry<'a, T> {
    fn cmp(&self, other: &Self) -> Ordering {
        self.partial_cmp(other).unwrap_or(Ordering::Equal)
    }
}

impl<T> SpatialIndex<T> for QuadTree<T> {
    fn insert(&mut self, object: SpatialObject<T>) {
        if self.root.insert(object, self.capacity) {
            self.size += 1;
        }
    }
    
    fn query_range(&self, range: &Rectangle) -> Vec<&SpatialObject<T>> {
        let mut results = Vec::new();
        self.root.query_range(range, &mut results);
        results
    }
    
    fn query_nearest(&self, point: &Point, k: usize) -> Vec<&SpatialObject<T>> {
        let mut heap = BinaryHeap::new();
        self.root.query_nearest(point, &mut heap, k);
        
        let mut results: Vec<_> = heap.into_iter().map(|entry| entry.object).collect();
        results.reverse(); // Convert from max-heap to min order
        results
    }
    
    fn query_within_distance(&self, point: &Point, distance: f64) -> Vec<&SpatialObject<T>> {
        let range = Rectangle::new(
            point.x - distance,
            point.y - distance,
            point.x + distance,
            point.y + distance,
        );
        
        self.query_range(&range)
            .into_iter()
            .filter(|obj| point.distance_to(&obj.point) <= distance)
            .collect()
    }
    
    fn size(&self) -> usize {
        self.size
    }
}
```

## R-Tree Implementation

```rust
// src/rtree.rs
use crate::types::{Point, Rectangle, SpatialObject, SpatialIndex};
use std::collections::BinaryHeap;

pub struct RTree<T> {
    root: Option<Box<RTreeNode<T>>>,
    size: usize,
    max_entries: usize,
    min_entries: usize,
}

struct RTreeNode<T> {
    boundary: Rectangle,
    entries: Vec<RTreeEntry<T>>,
    is_leaf: bool,
}

enum RTreeEntry<T> {
    Internal {
        boundary: Rectangle,
        child: Box<RTreeNode<T>>,
    },
    Leaf {
        object: SpatialObject<T>,
    },
}

impl<T> RTree<T> {
    pub fn new(max_entries: usize) -> Self {
        let min_entries = max_entries / 2;
        Self {
            root: None,
            size: 0,
            max_entries,
            min_entries,
        }
    }
    
    fn choose_leaf(&self, object: &SpatialObject<T>) -> Option<&RTreeNode<T>> {
        let mut current = self.root.as_deref()?;
        
        while !current.is_leaf {
            let mut best_child = None;
            let mut best_enlargement = f64::INFINITY;
            let mut best_area = f64::INFINITY;
            
            for entry in &current.entries {
                if let RTreeEntry::Internal { boundary, child } = entry {
                    let point_rect = Rectangle::new(
                        object.point.x, object.point.y,
                        object.point.x, object.point.y
                    );
                    
                    let enlarged = boundary.union(&point_rect);
                    let enlargement = enlarged.area() - boundary.area();
                    
                    if enlargement < best_enlargement || 
                       (enlargement == best_enlargement && boundary.area() < best_area) {
                        best_enlargement = enlargement;
                        best_area = boundary.area();
                        best_child = Some(child.as_ref());
                    }
                }
            }
            
            current = best_child?;
        }
        
        Some(current)
    }
    
    fn insert_recursive(&mut self, object: SpatialObject<T>, node: &mut RTreeNode<T>) -> Option<RTreeNode<T>> {
        if node.is_leaf {
            // Insert into leaf node
            let point_rect = Rectangle::new(
                object.point.x, object.point.y,
                object.point.x, object.point.y
            );
            
            node.boundary = node.boundary.union(&point_rect);
            node.entries.push(RTreeEntry::Leaf { object });
            
            // Split if necessary
            if node.entries.len() > self.max_entries {
                return Some(self.split_node(node));
            }
        } else {
            // Find best child to insert into
            let mut best_idx = 0;
            let mut best_enlargement = f64::INFINITY;
            let mut best_area = f64::INFINITY;
            
            for (i, entry) in node.entries.iter().enumerate() {
                if let RTreeEntry::Internal { boundary, .. } = entry {
                    let point_rect = Rectangle::new(
                        object.point.x, object.point.y,
                        object.point.x, object.point.y
                    );
                    
                    let enlarged = boundary.union(&point_rect);
                    let enlargement = enlarged.area() - boundary.area();
                    
                    if enlargement < best_enlargement || 
                       (enlargement == best_enlargement && boundary.area() < best_area) {
                        best_enlargement = enlargement;
                        best_area = boundary.area();
                        best_idx = i;
                    }
                }
            }
            
            // Insert into chosen child
            if let RTreeEntry::Internal { boundary, child } = &mut node.entries[best_idx] {
                if let Some(split_node) = self.insert_recursive(object, child) {
                    // Child was split, need to add new node
                    let split_boundary = split_node.boundary;
                    node.entries.push(RTreeEntry::Internal {
                        boundary: split_boundary,
                        child: Box::new(split_node),
                    });
                    
                    // Update boundary
                    *boundary = child.boundary;
                    node.update_boundary();
                    
                    // Split this node if necessary
                    if node.entries.len() > self.max_entries {
                        return Some(self.split_node(node));
                    }
                } else {
                    // Update boundary after insertion
                    *boundary = child.boundary;
                    node.update_boundary();
                }
            }
        }
        
        None
    }
    
    fn split_node(&self, node: &mut RTreeNode<T>) -> RTreeNode<T> {
        // Simple linear split - pick two most distant entries as seeds
        let mut best_separation = 0.0;
        let mut seed1 = 0;
        let mut seed2 = 1;
        
        for i in 0..node.entries.len() {
            for j in (i + 1)..node.entries.len() {
                let rect1 = self.entry_boundary(&node.entries[i]);
                let rect2 = self.entry_boundary(&node.entries[j]);
                let union = rect1.union(&rect2);
                let separation = union.area() - rect1.area() - rect2.area();
                
                if separation > best_separation {
                    best_separation = separation;
                    seed1 = i;
                    seed2 = j;
                }
            }
        }
        
        // Create two new groups
        let mut group1 = Vec::new();
        let mut group2 = Vec::new();
        
        if seed2 < seed1 {
            std::mem::swap(&mut seed1, &mut seed2);
        }
        
        group2.push(node.entries.remove(seed2));
        group1.push(node.entries.remove(seed1));
        
        // Distribute remaining entries
        for entry in node.entries.drain(..) {
            let rect = self.entry_boundary(&entry);
            
            if group1.len() + (node.entries.len() - group2.len()) <= self.min_entries {
                group1.push(entry);
            } else if group2.len() + (node.entries.len() - group1.len()) <= self.min_entries {
                group2.push(entry);
            } else {
                // Choose group with least enlargement
                let boundary1 = self.calculate_boundary(&group1);
                let boundary2 = self.calculate_boundary(&group2);
                
                let enlargement1 = boundary1.union(&rect).area() - boundary1.area();
                let enlargement2 = boundary2.union(&rect).area() - boundary2.area();
                
                if enlargement1 <= enlargement2 {
                    group1.push(entry);
                } else {
                    group2.push(entry);
                }
            }
        }
        
        // Update original node with group1
        node.entries = group1;
        node.update_boundary();
        
        // Create new node with group2
        let mut new_node = RTreeNode {
            boundary: self.calculate_boundary(&group2),
            entries: group2,
            is_leaf: node.is_leaf,
        };
        new_node.update_boundary();
        
        new_node
    }
    
    fn entry_boundary(&self, entry: &RTreeEntry<T>) -> Rectangle {
        match entry {
            RTreeEntry::Internal { boundary, .. } => *boundary,
            RTreeEntry::Leaf { object } => Rectangle::new(
                object.point.x, object.point.y,
                object.point.x, object.point.y
            ),
        }
    }
    
    fn calculate_boundary(&self, entries: &[RTreeEntry<T>]) -> Rectangle {
        if entries.is_empty() {
            return Rectangle::new(0.0, 0.0, 0.0, 0.0);
        }
        
        let mut boundary = self.entry_boundary(&entries[0]);
        for entry in entries.iter().skip(1) {
            boundary = boundary.union(&self.entry_boundary(entry));
        }
        boundary
    }
}

impl<T> RTreeNode<T> {
    fn update_boundary(&mut self) {
        if self.entries.is_empty() {
            return;
        }
        
        let first_boundary = match &self.entries[0] {
            RTreeEntry::Internal { boundary, .. } => *boundary,
            RTreeEntry::Leaf { object } => Rectangle::new(
                object.point.x, object.point.y,
                object.point.x, object.point.y
            ),
        };
        
        self.boundary = self.entries.iter().skip(1).fold(first_boundary, |acc, entry| {
            let entry_boundary = match entry {
                RTreeEntry::Internal { boundary, .. } => *boundary,
                RTreeEntry::Leaf { object } => Rectangle::new(
                    object.point.x, object.point.y,
                    object.point.x, object.point.y
                ),
            };
            acc.union(&entry_boundary)
        });
    }
    
    fn query_range<'a>(&'a self, range: &Rectangle, results: &mut Vec<&'a SpatialObject<T>>) {
        if !self.boundary.intersects(range) {
            return;
        }
        
        for entry in &self.entries {
            match entry {
                RTreeEntry::Internal { boundary, child } => {
                    if boundary.intersects(range) {
                        child.query_range(range, results);
                    }
                }
                RTreeEntry::Leaf { object } => {
                    if range.contains_point(&object.point) {
                        results.push(object);
                    }
                }
            }
        }
    }
}

impl<T> SpatialIndex<T> for RTree<T> {
    fn insert(&mut self, object: SpatialObject<T>) {
        if self.root.is_none() {
            let boundary = Rectangle::new(
                object.point.x, object.point.y,
                object.point.x, object.point.y
            );
            
            self.root = Some(Box::new(RTreeNode {
                boundary,
                entries: vec![RTreeEntry::Leaf { object }],
                is_leaf: true,
            }));
            self.size = 1;
            return;
        }
        
        let root = self.root.as_mut().unwrap();
        if let Some(split_node) = self.insert_recursive(object, root) {
            // Root was split, create new root
            let old_root_boundary = root.boundary;
            let new_node_boundary = split_node.boundary;
            
            let new_root = RTreeNode {
                boundary: old_root_boundary.union(&new_node_boundary),
                entries: vec![
                    RTreeEntry::Internal {
                        boundary: old_root_boundary,
                        child: std::mem::replace(root, split_node).into(),
                    },
                    RTreeEntry::Internal {
                        boundary: new_node_boundary,
                        child: Box::new(split_node),
                    },
                ],
                is_leaf: false,
            };
            
            self.root = Some(Box::new(new_root));
        }
        
        self.size += 1;
    }
    
    fn query_range(&self, range: &Rectangle) -> Vec<&SpatialObject<T>> {
        let mut results = Vec::new();
        if let Some(root) = &self.root {
            root.query_range(range, &mut results);
        }
        results
    }
    
    fn query_nearest(&self, point: &Point, k: usize) -> Vec<&SpatialObject<T>> {
        // Simplified nearest neighbor - could be optimized with priority queue
        let large_range = Rectangle::new(
            point.x - 1000.0, point.y - 1000.0,
            point.x + 1000.0, point.y + 1000.0
        );
        
        let mut candidates = self.query_range(&large_range);
        candidates.sort_by(|a, b| {
            let dist_a = point.distance_to(&a.point);
            let dist_b = point.distance_to(&b.point);
            dist_a.partial_cmp(&dist_b).unwrap_or(std::cmp::Ordering::Equal)
        });
        
        candidates.into_iter().take(k).collect()
    }
    
    fn query_within_distance(&self, point: &Point, distance: f64) -> Vec<&SpatialObject<T>> {
        let range = Rectangle::new(
            point.x - distance, point.y - distance,
            point.x + distance, point.y + distance
        );
        
        self.query_range(&range)
            .into_iter()
            .filter(|obj| point.distance_to(&obj.point) <= distance)
            .collect()
    }
    
    fn size(&self) -> usize {
        self.size
    }
}
```

## Geohash Implementation

```rust
// src/geohash.rs
use crate::types::Point;
use std::collections::HashMap;

const BASE32_CHARS: &[u8] = b"0123456789bcdefghjkmnpqrstuvwxyz";
const BASE32_MAP: [i8; 256] = {
    let mut map = [-1i8; 256];
    let mut i = 0;
    while i < BASE32_CHARS.len() {
        map[BASE32_CHARS[i] as usize] = i as i8;
        i += 1;
    }
    map
};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Geohash {
    pub hash: String,
    pub precision: usize,
}

impl Geohash {
    pub fn encode(latitude: f64, longitude: f64, precision: usize) -> Self {
        assert!((-90.0..=90.0).contains(&latitude));
        assert!((-180.0..=180.0).contains(&longitude));
        assert!((1..=12).contains(&precision));
        
        let mut lat_range = [-90.0, 90.0];
        let mut lon_range = [-180.0, 180.0];
        
        let mut bits = Vec::new();
        let mut even_bit = true; // Start with longitude
        
        while bits.len() < precision * 5 {
            if even_bit {
                let mid = (lon_range[0] + lon_range[1]) / 2.0;
                if longitude >= mid {
                    bits.push(1);
                    lon_range[0] = mid;
                } else {
                    bits.push(0);
                    lon_range[1] = mid;
                }
            } else {
                let mid = (lat_range[0] + lat_range[1]) / 2.0;
                if latitude >= mid {
                    bits.push(1);
                    lat_range[0] = mid;
                } else {
                    bits.push(0);
                    lat_range[1] = mid;
                }
            }
            even_bit = !even_bit;
        }
        
        // Convert bits to base32 string
        let mut hash = String::new();
        for chunk in bits.chunks(5) {
            let mut value = 0u8;
            for (i, &bit) in chunk.iter().enumerate() {
                if bit == 1 {
                    value |= 1 << (4 - i);
                }
            }
            hash.push(BASE32_CHARS[value as usize] as char);
        }
        
        Self { hash, precision }
    }
    
    pub fn decode(&self) -> (f64, f64, f64, f64) {
        let mut lat_range = [-90.0, 90.0];
        let mut lon_range = [-180.0, 180.0];
        let mut even_bit = true;
        
        for ch in self.hash.chars() {
            let value = BASE32_MAP[ch as usize];
            if value == -1 {
                panic!("Invalid geohash character: {}", ch);
            }
            
            for i in (0..5).rev() {
                let bit = (value as u8 >> i) & 1;
                
                if even_bit {
                    let mid = (lon_range[0] + lon_range[1]) / 2.0;
                    if bit == 1 {
                        lon_range[0] = mid;
                    } else {
                        lon_range[1] = mid;
                    }
                } else {
                    let mid = (lat_range[0] + lat_range[1]) / 2.0;
                    if bit == 1 {
                        lat_range[0] = mid;
                    } else {
                        lat_range[1] = mid;
                    }
                }
                even_bit = !even_bit;
            }
        }
        
        let lat_center = (lat_range[0] + lat_range[1]) / 2.0;
        let lon_center = (lon_range[0] + lon_range[1]) / 2.0;
        let lat_error = (lat_range[1] - lat_range[0]) / 2.0;
        let lon_error = (lon_range[1] - lon_range[0]) / 2.0;
        
        (lat_center, lon_center, lat_error, lon_error)
    }
    
    pub fn neighbors(&self) -> HashMap<String, String> {
        let (lat, lon, lat_err, lon_err) = self.decode();
        let precision = self.precision;
        
        let mut neighbors = HashMap::new();
        
        let directions = [
            ("north", lat + 2.0 * lat_err, lon),
            ("south", lat - 2.0 * lat_err, lon),
            ("east", lat, lon + 2.0 * lon_err),
            ("west", lat, lon - 2.0 * lon_err),
            ("northeast", lat + 2.0 * lat_err, lon + 2.0 * lon_err),
            ("northwest", lat + 2.0 * lat_err, lon - 2.0 * lon_err),
            ("southeast", lat - 2.0 * lat_err, lon + 2.0 * lon_err),
            ("southwest", lat - 2.0 * lat_err, lon - 2.0 * lon_err),
        ];
        
        for (direction, new_lat, new_lon) in directions {
            let bounded_lat = new_lat.clamp(-90.0, 90.0);
            let bounded_lon = if new_lon > 180.0 {
                new_lon - 360.0
            } else if new_lon < -180.0 {
                new_lon + 360.0
            } else {
                new_lon
            };
            
            let neighbor = Self::encode(bounded_lat, bounded_lon, precision);
            neighbors.insert(direction.to_string(), neighbor.hash);
        }
        
        neighbors
    }
    
    pub fn common_prefix(&self, other: &Geohash) -> String {
        let mut common = String::new();
        let chars1: Vec<char> = self.hash.chars().collect();
        let chars2: Vec<char> = other.hash.chars().collect();
        
        for (c1, c2) in chars1.iter().zip(chars2.iter()) {
            if c1 == c2 {
                common.push(*c1);
            } else {
                break;
            }
        }
        
        common
    }
    
    pub fn distance_estimate(&self, other: &Geohash) -> f64 {
        let common_len = self.common_prefix(other).len();
        
        // Rough distance estimation based on common prefix length
        match common_len {
            0 => 20000.0,   // Different continents
            1 => 5000.0,    // Different countries
            2 => 1250.0,    // Different regions
            3 => 156.0,     // Different cities
            4 => 39.0,      // Different neighborhoods
            5 => 4.9,       // Different blocks
            6 => 1.2,       // Same block
            7 => 0.15,      // Same building
            _ => 0.037,     // Same room
        }
    }
}

pub struct GeohashIndex<T> {
    data: HashMap<String, Vec<(Point, T)>>,
    precision: usize,
}

impl<T> GeohashIndex<T> {
    pub fn new(precision: usize) -> Self {
        Self {
            data: HashMap::new(),
            precision,
        }
    }
    
    pub fn insert(&mut self, point: Point, data: T) {
        let geohash = Geohash::encode(point.y, point.x, self.precision);
        self.data.entry(geohash.hash).or_default().push((point, data));
    }
    
    pub fn query_cell(&self, geohash: &str) -> Vec<&(Point, T)> {
        self.data.get(geohash).map_or(Vec::new(), |items| {
            items.iter().collect()
        })
    }
    
    pub fn query_nearby(&self, point: Point, include_neighbors: bool) -> Vec<&(Point, T)> {
        let geohash = Geohash::encode(point.y, point.x, self.precision);
        let mut results = self.query_cell(&geohash.hash);
        
        if include_neighbors {
            let neighbors = geohash.neighbors();
            for neighbor_hash in neighbors.values() {
                results.extend(self.query_cell(neighbor_hash));
            }
        }
        
        results
    }
    
    pub fn query_prefix(&self, prefix: &str) -> Vec<&(Point, T)> {
        let mut results = Vec::new();
        for (hash, items) in &self.data {
            if hash.starts_with(prefix) {
                results.extend(items.iter());
            }
        }
        results
    }
}
```

## Spatial Hash Grid Implementation

```rust
// src/spatial_hash.rs
use crate::types::{Point, Rectangle, SpatialObject, SpatialIndex};
use std::collections::HashMap;

pub struct SpatialHashGrid<T> {
    cells: HashMap<(i32, i32), Vec<SpatialObject<T>>>,
    cell_size: f64,
    size: usize,
}

impl<T> SpatialHashGrid<T> {
    pub fn new(cell_size: f64) -> Self {
        Self {
            cells: HashMap::new(),
            cell_size,
            size: 0,
        }
    }
    
    fn get_cell_coordinates(&self, point: &Point) -> (i32, i32) {
        let x = (point.x / self.cell_size).floor() as i32;
        let y = (point.y / self.cell_size).floor() as i32;
        (x, y)
    }
    
    fn get_cells_for_range(&self, range: &Rectangle) -> Vec<(i32, i32)> {
        let min_x = (range.min_x / self.cell_size).floor() as i32;
        let max_x = (range.max_x / self.cell_size).floor() as i32;
        let min_y = (range.min_y / self.cell_size).floor() as i32;
        let max_y = (range.max_y / self.cell_size).floor() as i32;
        
        let mut cells = Vec::new();
        for x in min_x..=max_x {
            for y in min_y..=max_y {
                cells.push((x, y));
            }
        }
        cells
    }
    
    pub fn clear(&mut self) {
        self.cells.clear();
        self.size = 0;
    }
    
    pub fn get_load_factor(&self) -> f64 {
        if self.cells.is_empty() {
            return 0.0;
        }
        
        self.size as f64 / self.cells.len() as f64
    }
    
    pub fn get_statistics(&self) -> SpatialHashStats {
        if self.cells.is_empty() {
            return SpatialHashStats::default();
        }
        
        let mut min_objects = usize::MAX;
        let mut max_objects = 0;
        let mut total_objects = 0;
        
        for cell in self.cells.values() {
            let count = cell.len();
            min_objects = min_objects.min(count);
            max_objects = max_objects.max(count);
            total_objects += count;
        }
        
        SpatialHashStats {
            total_cells: self.cells.len(),
            total_objects,
            min_objects_per_cell: min_objects,
            max_objects_per_cell: max_objects,
            avg_objects_per_cell: total_objects as f64 / self.cells.len() as f64,
            load_factor: self.get_load_factor(),
        }
    }
}

#[derive(Debug, Default)]
pub struct SpatialHashStats {
    pub total_cells: usize,
    pub total_objects: usize,
    pub min_objects_per_cell: usize,
    pub max_objects_per_cell: usize,
    pub avg_objects_per_cell: f64,
    pub load_factor: f64,
}

impl<T> SpatialIndex<T> for SpatialHashGrid<T> {
    fn insert(&mut self, object: SpatialObject<T>) {
        let cell_coords = self.get_cell_coordinates(&object.point);
        self.cells.entry(cell_coords).or_default().push(object);
        self.size += 1;
    }
    
    fn query_range(&self, range: &Rectangle) -> Vec<&SpatialObject<T>> {
        let mut results = Vec::new();
        let cells = self.get_cells_for_range(range);
        
        for cell_coords in cells {
            if let Some(objects) = self.cells.get(&cell_coords) {
                for object in objects {
                    if range.contains_point(&object.point) {
                        results.push(object);
                    }
                }
            }
        }
        
        results
    }
    
    fn query_nearest(&self, point: &Point, k: usize) -> Vec<&SpatialObject<T>> {
        let center_cell = self.get_cell_coordinates(point);
        let mut candidates = Vec::new();
        let mut search_radius = 1;
        
        // Expand search radius until we have enough candidates
        while candidates.len() < k * 2 && search_radius < 10 {
            for dx in -search_radius..=search_radius {
                for dy in -search_radius..=search_radius {
                    // Only check boundary cells on each expansion
                    if dx.abs() != search_radius && dy.abs() != search_radius {
                        continue;
                    }
                    
                    let cell_coords = (center_cell.0 + dx, center_cell.1 + dy);
                    if let Some(objects) = self.cells.get(&cell_coords) {
                        for object in objects {
                            let distance = point.distance_to(&object.point);
                            candidates.push((object, distance));
                        }
                    }
                }
            }
            search_radius += 1;
        }
        
        // Sort by distance and take k nearest
        candidates.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        candidates.into_iter().take(k).map(|(obj, _)| obj).collect()
    }
    
    fn query_within_distance(&self, point: &Point, distance: f64) -> Vec<&SpatialObject<T>> {
        let range = Rectangle::new(
            point.x - distance,
            point.y - distance, 
            point.x + distance,
            point.y + distance,
        );
        
        self.query_range(&range)
            .into_iter()
            .filter(|obj| point.distance_to(&obj.point) <= distance)
            .collect()
    }
    
    fn size(&self) -> usize {
        self.size
    }
}
```

## Performance Testing and Benchmarks

```rust
// src/lib.rs
pub mod types;
pub mod quadtree;
pub mod rtree;
pub mod geohash;
pub mod spatial_hash;

pub use types::*;
pub use quadtree::QuadTree;
pub use rtree::RTree;
pub use geohash::{Geohash, GeohashIndex};
pub use spatial_hash::SpatialHashGrid;

#[cfg(test)]
mod tests {
    use super::*;
    use rand::{Rng, SeedableRng};
    use rand::rngs::StdRng;

    fn generate_test_data(count: usize, seed: u64) -> Vec<SpatialObject<i32>> {
        let mut rng = StdRng::seed_from_u64(seed);
        (0..count)
            .map(|i| {
                let x = rng.gen_range(-1000.0..1000.0);
                let y = rng.gen_range(-1000.0..1000.0);
                SpatialObject::new(Point::new(x, y), i as i32)
            })
            .collect()
    }

    #[test]
    fn test_quadtree_basic_operations() {
        let boundary = Rectangle::new(-100.0, -100.0, 100.0, 100.0);
        let mut qtree = QuadTree::new(boundary, 4);
        
        let objects = generate_test_data(100, 42);
        for obj in objects {
            qtree.insert(obj);
        }
        
        assert_eq!(qtree.size(), 100);
        
        let query_range = Rectangle::new(-50.0, -50.0, 50.0, 50.0);
        let results = qtree.query_range(&query_range);
        assert!(!results.is_empty());
        
        let nearest = qtree.query_nearest(&Point::new(0.0, 0.0), 5);
        assert_eq!(nearest.len(), 5);
    }

    #[test]
    fn test_rtree_basic_operations() {
        let mut rtree = RTree::new(16);
        
        let objects = generate_test_data(100, 42);
        for obj in objects {
            rtree.insert(obj);
        }
        
        assert_eq!(rtree.size(), 100);
        
        let query_range = Rectangle::new(-50.0, -50.0, 50.0, 50.0);
        let results = rtree.query_range(&query_range);
        assert!(!results.is_empty());
    }

    #[test]
    fn test_spatial_hash_basic_operations() {
        let mut spatial_hash = SpatialHashGrid::new(50.0);
        
        let objects = generate_test_data(100, 42);
        for obj in objects {
            spatial_hash.insert(obj);
        }
        
        assert_eq!(spatial_hash.size(), 100);
        
        let query_range = Rectangle::new(-50.0, -50.0, 50.0, 50.0);
        let results = spatial_hash.query_range(&query_range);
        assert!(!results.is_empty());
    }

    #[test]
    fn test_geohash_encoding_decoding() {
        let lat = 47.6062;
        let lon = -122.3321;
        let precision = 8;
        
        let geohash = Geohash::encode(lat, lon, precision);
        assert_eq!(geohash.precision, precision);
        
        let (decoded_lat, decoded_lon, _, _) = geohash.decode();
        assert!((decoded_lat - lat).abs() < 0.001);
        assert!((decoded_lon - lon).abs() < 0.001);
    }

    #[test]
    fn test_geohash_neighbors() {
        let geohash = Geohash::encode(47.6062, -122.3321, 6);
        let neighbors = geohash.neighbors();
        
        assert_eq!(neighbors.len(), 8);
        assert!(neighbors.contains_key("north"));
        assert!(neighbors.contains_key("south"));
        assert!(neighbors.contains_key("east"));
        assert!(neighbors.contains_key("west"));
    }
}

// Example usage and demo
pub fn demo() {
    println!("Spatial Indexing Demo");
    println!("====================");
    
    // Generate test data
    let mut rng = rand::thread_rng();
    let mut objects = Vec::new();
    
    for i in 0..1000 {
        let x = rng.gen_range(-1000.0..1000.0);
        let y = rng.gen_range(-1000.0..1000.0);
        objects.push(SpatialObject::new(Point::new(x, y), format!("Object {}", i)));
    }
    
    // Test QuadTree
    println!("\nQuadTree Performance:");
    let boundary = Rectangle::new(-1000.0, -1000.0, 1000.0, 1000.0);
    let mut qtree = QuadTree::new(boundary, 10);
    
    let start = std::time::Instant::now();
    for obj in &objects {
        qtree.insert(obj.clone());
    }
    println!("  Insert time: {:?}", start.elapsed());
    
    let query_point = Point::new(0.0, 0.0);
    let start = std::time::Instant::now();
    let nearest = qtree.query_nearest(&query_point, 10);
    println!("  Nearest query time: {:?}", start.elapsed());
    println!("  Found {} nearest objects", nearest.len());
    
    // Test R-Tree
    println!("\nR-Tree Performance:");
    let mut rtree = RTree::new(16);
    
    let start = std::time::Instant::now();
    for obj in &objects {
        rtree.insert(obj.clone());
    }
    println!("  Insert time: {:?}", start.elapsed());
    
    let query_range = Rectangle::new(-100.0, -100.0, 100.0, 100.0);
    let start = std::time::Instant::now();
    let range_results = rtree.query_range(&query_range);
    println!("  Range query time: {:?}", start.elapsed());
    println!("  Found {} objects in range", range_results.len());
    
    // Test Spatial Hash Grid
    println!("\nSpatial Hash Grid Performance:");
    let mut spatial_hash = SpatialHashGrid::new(100.0);
    
    let start = std::time::Instant::now();
    for obj in &objects {
        spatial_hash.insert(obj.clone());
    }
    println!("  Insert time: {:?}", start.elapsed());
    
    let start = std::time::Instant::now();
    let hash_nearest = spatial_hash.query_nearest(&query_point, 10);
    println!("  Nearest query time: {:?}", start.elapsed());
    println!("  Found {} nearest objects", hash_nearest.len());
    
    let stats = spatial_hash.get_statistics();
    println!("  Grid statistics: {:?}", stats);
    
    // Test Geohash
    println!("\nGeohash Demo:");
    let seattle = Point::new(-122.3321, 47.6062);
    let portland = Point::new(-122.6765, 45.5152);
    
    let seattle_hash = Geohash::encode(seattle.y, seattle.x, 8);
    let portland_hash = Geohash::encode(portland.y, portland.x, 8);
    
    println!("  Seattle geohash: {}", seattle_hash.hash);
    println!("  Portland geohash: {}", portland_hash.hash);
    println!("  Common prefix: '{}'", seattle_hash.common_prefix(&portland_hash));
    println!("  Distance estimate: {:.1} km", seattle_hash.distance_estimate(&portland_hash));
}
```

## Main Application

```rust
// src/main.rs
use spatial_indexing::demo;

fn main() {
    demo();
}
```

## Benchmarks

```rust
// benches/spatial_benchmark.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use spatial_indexing::*;
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;

fn generate_test_data(count: usize, seed: u64) -> Vec<SpatialObject<i32>> {
    let mut rng = StdRng::seed_from_u64(seed);
    (0..count)
        .map(|i| {
            let x = rng.gen_range(-1000.0..1000.0);
            let y = rng.gen_range(-1000.0..1000.0);
            SpatialObject::new(Point::new(x, y), i as i32)
        })
        .collect()
}

fn benchmark_insertions(c: &mut Criterion) {
    let mut group = c.benchmark_group("insertions");
    
    for size in [100, 1000, 10000].iter() {
        let objects = generate_test_data(*size, 42);
        
        group.bench_with_input(BenchmarkId::new("quadtree", size), size, |b, _| {
            b.iter(|| {
                let boundary = Rectangle::new(-1000.0, -1000.0, 1000.0, 1000.0);
                let mut qtree = QuadTree::new(boundary, 10);
                for obj in &objects {
                    qtree.insert(black_box(obj.clone()));
                }
            })
        });
        
        group.bench_with_input(BenchmarkId::new("rtree", size), size, |b, _| {
            b.iter(|| {
                let mut rtree = RTree::new(16);
                for obj in &objects {
                    rtree.insert(black_box(obj.clone()));
                }
            })
        });
        
        group.bench_with_input(BenchmarkId::new("spatial_hash", size), size, |b, _| {
            b.iter(|| {
                let mut spatial_hash = SpatialHashGrid::new(100.0);
                for obj in &objects {
                    spatial_hash.insert(black_box(obj.clone()));
                }
            })
        });
    }
    
    group.finish();
}

fn benchmark_range_queries(c: &mut Criterion) {
    let mut group = c.benchmark_group("range_queries");
    
    let objects = generate_test_data(10000, 42);
    let query_range = Rectangle::new(-100.0, -100.0, 100.0, 100.0);
    
    // Prepare data structures
    let boundary = Rectangle::new(-1000.0, -1000.0, 1000.0, 1000.0);
    let mut qtree = QuadTree::new(boundary, 10);
    let mut rtree = RTree::new(16);
    let mut spatial_hash = SpatialHashGrid::new(100.0);
    
    for obj in &objects {
        qtree.insert(obj.clone());
        rtree.insert(obj.clone());
        spatial_hash.insert(obj.clone());
    }
    
    group.bench_function("quadtree", |b| {
        b.iter(|| qtree.query_range(black_box(&query_range)))
    });
    
    group.bench_function("rtree", |b| {
        b.iter(|| rtree.query_range(black_box(&query_range)))
    });
    
    group.bench_function("spatial_hash", |b| {
        b.iter(|| spatial_hash.query_range(black_box(&query_range)))
    });
    
    group.finish();
}

fn benchmark_nearest_neighbor(c: &mut Criterion) {
    let mut group = c.benchmark_group("nearest_neighbor");
    
    let objects = generate_test_data(10000, 42);
    let query_point = Point::new(0.0, 0.0);
    
    // Prepare data structures
    let boundary = Rectangle::new(-1000.0, -1000.0, 1000.0, 1000.0);
    let mut qtree = QuadTree::new(boundary, 10);
    let mut spatial_hash = SpatialHashGrid::new(100.0);
    
    for obj in &objects {
        qtree.insert(obj.clone());
        spatial_hash.insert(obj.clone());
    }
    
    group.bench_function("quadtree", |b| {
        b.iter(|| qtree.query_nearest(black_box(&query_point), black_box(10)))
    });
    
    group.bench_function("spatial_hash", |b| {
        b.iter(|| spatial_hash.query_nearest(black_box(&query_point), black_box(10)))
    });
    
    group.finish();
}

criterion_group!(benches, benchmark_insertions, benchmark_range_queries, benchmark_nearest_neighbor);
criterion_main!(benches);
```

## Usage

Run the demo:
```bash
cargo run --release
```

Run tests:
```bash
cargo test
```

Run benchmarks:
```bash
cargo bench
```

## Key Features

1. **Memory Safety**: Leverages Rust's ownership system to prevent spatial indexing bugs
2. **Generic Design**: Works with any data type via generics and traits
3. **Performance Optimized**: Efficient algorithms with careful memory management
4. **Comprehensive**: Multiple spatial indexing strategies for different use cases
5. **Well Tested**: Unit tests and benchmarks for validation and performance analysis

This implementation provides a solid foundation for spatial applications requiring high performance and memory safety.