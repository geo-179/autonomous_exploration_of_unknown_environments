from typing import List, Optional
from shapely.geometry import Polygon, Point, LineString
from shapely.geometry.base import BaseGeometry
import math
import numpy as np

class Map:
    """
    Represents a 2D map with a rectangular boundary, obstacles, and beacons.

    This class supports checking intersections between a given geometry and
    the map's boundary/obstacles, as well as adding obstacles and beacons.

    Attributes:
        boundary (LineString): The boundary of the map as a rectangular polygon's edge.
        obstacles (List[BaseGeometry]): A list of geometric obstacles on the map.
        beacons (List[Point]): A list of beacon positions.
    """
    def __init__(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
        obstacles: Optional[List[BaseGeometry]] = None,
        beacons: Optional[List[Point]] = None
    ) -> None:
        """
        Initialize the map with a rectangular boundary.

        The rectangle is defined by the lower-left corner (x_min, y_min) and
        the upper-right corner (x_max, y_max).

        Args:
            x_min (float): Minimum x-coordinate (left boundary).
            y_min (float): Minimum y-coordinate (bottom boundary).
            x_max (float): Maximum x-coordinate (right boundary).
            y_max (float): Maximum y-coordinate (top boundary).
            obstacles (Optional[List[BaseGeometry]]): An optional list of obstacles.
        """
        # Create a rectangular polygon and then use its boundary (LineString)
        self.boundary: LineString = Polygon([
            (x_min, y_min),
            (x_max, y_min),
            (x_max, y_max),
            (x_min, y_max)
        ]).boundary
        self.obstacles: List[BaseGeometry] = [] if obstacles is None else obstacles
        self.beacons: List[Point] = [] if beacons is None else beacons

    def _add_obstacle(self, obstacle: BaseGeometry) -> None:
        """
        Add an obstacle to the map.

        Args:
            obstacle (BaseGeometry): A geometric object representing an obstacle.
        """
        self.obstacles.append(obstacle)

    def _add_beacon(self, beacon: Point) -> None:
        """
        Add a beacon to the map.

        Args:
            beacon (Point): A point representing the beacon's location.
        """
        self.beacons.append(beacon)

    def return_se_to_closest_beacon(self, point: np.ndarray) -> float:
        """
        Calculate the Squared Error (SE) to the closest beacon.

        Args:
            point (np.ndarray): The point to calculate distance from [x, y] or [x, y, 0].

        Returns:
            float: MSE to the closest beacon, or -10e5 if no beacons exist.
        """
        if not self.beacons:
            return 10e5

        # Convert numpy array point to Shapely Point for distance calculation
        shapely_point = Point(point[0], point[1])

        # Calculate squared distances to all beacons
        distances = [shapely_point.distance(beacon) for beacon in self.beacons]

        # Return the minimum squared distance
        return min(distances) ** 2

    def _extract_points(self, geom: BaseGeometry) -> List[Point]:
        """
        Extract representative points from a geometry.

        - For a Point, returns [geom].
        - For a MultiPoint, returns all its points.
        - For LineString or LinearRing, returns all vertices of the line.
        - For MultiLineString, returns all vertices from each line.
        - For GeometryCollection, recursively processes each geometry.
        - For Polygon, returns vertices along the boundary.

        Args:
            geom (BaseGeometry): The geometry to extract points from.

        Returns:
            List[Point]: A list of representative points extracted from the geometry.
        """
        points: List[Point] = []
        if geom.is_empty:
            return points

        if geom.geom_type == 'Point':
            points.append(geom)
        elif geom.geom_type == 'MultiPoint':
            points.extend(list(geom.geoms))
        elif geom.geom_type in ['LineString', 'LinearRing']:
            # Return all vertices of the line instead of just the midpoint
            points.extend([Point(p) for p in geom.coords])
        elif geom.geom_type == 'MultiLineString':
            for line in geom.geoms:
                points.extend([Point(p) for p in line.coords])
        elif geom.geom_type == 'Polygon':
            # Return points along the boundary instead of just the centroid
            boundary = geom.boundary
            points.extend([Point(p) for p in boundary.coords])
        elif geom.geom_type == 'GeometryCollection':
            for g in geom.geoms:
                points.extend(self._extract_points(g))
        else:
            # For other geometries, use the centroid as a fallback
            points.append(geom.centroid)
        return points

    def intersections(self, geom: BaseGeometry) -> List[Point]:
        """
        Find intersections between a given geometry and the map's features.

        Checks for intersections with the map's boundary and all obstacles,
        and returns representative intersection points.

        Args:
            geom (BaseGeometry): The geometry to check for intersections.

        Returns:
            List[Point]: A list of points where intersections occur.
        """
        intersections: List[Point] = []

        # Intersection with the map boundary
        boundary_intersection = self.boundary.intersection(geom)
        if not boundary_intersection.is_empty:
            intersections.extend(self._extract_points(boundary_intersection))

        # Intersection with each obstacle
        for obstacle in self.obstacles:
            obs_intersection = obstacle.intersection(geom)
            if not obs_intersection.is_empty:
                intersections.extend(self._extract_points(obs_intersection))

        return intersections

    def calc_lidar_point_cloud(self,
                               pos_true: np.array,
                               delta_theta: float,
                               r_max: float,
                               r_min: float):
        """Calculate the LiDAR point cloud for a given robot position."""
        # Create the line segments for the LiDAR rays
        ray_segments = []
        for theta in range(0, 360, delta_theta):
            x_end = pos_true[0] + r_max * math.cos(math.radians(theta))
            y_end = pos_true[1] + r_max * math.sin(math.radians(theta))
            ray_segments.append(LineString([(pos_true[0], pos_true[1]), (x_end, y_end)]))

        # Find closest intersection points
        point_cloud = []
        robot_pos = Point(pos_true[0], pos_true[1])
        for ray in ray_segments:
            intersections = self.intersections(ray)
            if intersections:
                # Find the closest intersection point
                closest_point = min(intersections, key=lambda p: robot_pos.distance(p))
                # Discard points outside the valid range
                distance = robot_pos.distance(closest_point)
                if r_min <= distance <= r_max:
                    point_cloud.append(closest_point)
            else:
                # No intersection, add the ray's endpoint
                point_cloud.append(Point(ray.coords[-1]))

        return [np.array([p.x - pos_true[0], p.y - pos_true[1], 0]) for p in point_cloud]


    def calc_beacon_positions(self, pos_true: np.array) -> List[np.array]:
        """Calculate the positions of beacons relative to the robot."""
        # Calculate the line segments from the robot to each beacon
        pos_true_shapely = Point([pos_true[0], pos_true[1]])
        beacon_positions = []
        for beacon in self.beacons:
            beacon_line = LineString([pos_true_shapely, beacon])
            intersections = self.intersections(beacon_line)
            if intersections:
                continue    # robot cannot see the beacon
            else:
                beacon_positions.append(np.array(
                    [beacon.x - pos_true[0], beacon.y - pos_true[1], 0]
                ))
        return beacon_positions

# Map for particle vs kalman mse
MAP = Map(-10, -10, 10, 10)

MAP._add_beacon(Point(8.75, 0))
MAP._add_beacon(Point(-8.75, 0))
MAP._add_beacon(Point(0, 8.75))
MAP._add_beacon(Point(0, -8.75))

for center_x in [-4, 4]:
    for center_y in [-4, 4]:
        radius = 2.5
        MAP._add_obstacle(Polygon([
            (center_x - radius, center_y - radius),
            (center_x + radius, center_y - radius),
            (center_x + radius, center_y + radius),
            (center_x - radius, center_y + radius)
        ]))

# Below are different maps for testing
# MAP = Map(-10, -10, 10, 10)

# for x in [-8.75, 0, 8.75]:
#     for y in [-8.75, 0, 8.75]:
#         # if x == 0 and y == 0:
#         #     continue
#         MAP._add_beacon(Point(x, y))

# for center_x in [-4, 4]:
#     for center_y in [-4, 4]:
#         radius = 2.5
#         MAP._add_obstacle(Polygon([
#             (center_x - radius, center_y - radius),
#             (center_x + radius, center_y - radius),
#             (center_x + radius, center_y + radius),
#             (center_x - radius, center_y + radius)
#         ]))


# MAP = Map(-15, -15, 15, 15)

# # Add a small number of beacons in asymmetric positions
# beacons = [
#     (12, -10),
#     (-7, 8),
#     (3, 13),
#     (-13, -5)
# ]

# for x, y in beacons:
#     MAP._add_beacon(Point(x, y))

# # Helper function to create circles (approximated by polygons)
# def create_circle(center_x, center_y, radius, num_points=24):
#     points = []
#     for i in range(num_points):
#         angle = 2 * math.pi * i / num_points
#         x = center_x + radius * math.cos(angle)
#         y = center_y + radius * math.sin(angle)
#         points.append((x, y))
#     return Polygon(points)

# # Add squares of different sizes in asymmetric positions
# squares = [
#     # (center_x, center_y, side_length)
#     (-9, -11, 3),
#     (6, -5, 4),
#     (11, 7, 2.5),
#     (-3, 10, 5),
#     (0, -7, 2),
# ]

# for cx, cy, side in squares:
#     half_side = side / 2
#     MAP._add_obstacle(Polygon([
#         (cx - half_side, cy - half_side),
#         (cx + half_side, cy - half_side),
#         (cx + half_side, cy + half_side),
#         (cx - half_side, cy + half_side)
#     ]))

# # Add triangles with different orientations
# triangles = [
#     # Each tuple contains three (x,y) vertex coordinates
#     [(-12, 0), (-8, 0), (-10, 4)],
#     [(2, 0), (8, 1), (5, 6)],
#     [(0, -13), (5, -10), (-2, -9)],
# ]

# for vertices in triangles:
#     MAP._add_obstacle(Polygon(vertices))

# # Add circles of different sizes
# circles = [
#     # (center_x, center_y, radius)
#     (3, 3, 2.7),
#     (-5, -3, 2),
#     (-1, 6, 1.5),
#     (7, 12, 2.3),
#     (13, -1, 1.8),
# ]

# for cx, cy, radius in circles:
#     MAP._add_obstacle(create_circle(cx, cy, radius))

# # Add one complex polygon
# MAP._add_obstacle(Polygon([
#     (-5, 13), (-3, 11), (0, 12), (1, 10),
#     (3, 11), (1, 8), (-2, 9), (-4, 7),
#     (-7, 10), (-6, 12)
# ]))
