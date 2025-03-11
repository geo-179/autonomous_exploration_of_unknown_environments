# slam_node.py
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from geometry_msgs.msg import PoseStamped, Vector3, Twist
from nav_msgs.msg import OccupancyGrid, Path
from visualization_msgs.msg import Marker, MarkerArray
from multi_slam.Map import Map
from multi_slam.Localization import Localization
from multi_slam.Mapping import Mapping
import numpy as np
from scipy.linalg import expm
from sensor_msgs_py.point_cloud2 import read_points
import math
from std_msgs.msg import Float32MultiArray

class SLAMNode(Node):
    def __init__(self):
        super().__init__("slam_node")
        
        # Parameters
        self.declare_parameter('map_size_x', 100.0)
        self.declare_parameter('map_size_y', 100.0)
        self.declare_parameter('map_origin_x', -50.0)
        self.declare_parameter('map_origin_y', -50.0)
        self.declare_parameter('grid_size', 0.1)
        self.declare_parameter('num_particles', 100)
        self.declare_parameter('position_std_dev', 0.1)
        self.declare_parameter('use_proposed_control', True)  # Flag to switch between control methods
        
        # Get parameters
        map_size_x = self.get_parameter('map_size_x').value
        map_size_y = self.get_parameter('map_size_y').value
        map_origin_x = self.get_parameter('map_origin_x').value
        map_origin_y = self.get_parameter('map_origin_y').value
        grid_size = self.get_parameter('grid_size').value
        num_particles = self.get_parameter('num_particles').value
        position_std_dev = self.get_parameter('position_std_dev').value
        self.use_proposed_control = self.get_parameter('use_proposed_control').value
        
        # Initialize Map and Localization
        self.map = Mapping(
            map_size=(map_size_x, map_size_y),
            map_origin=(map_origin_x, map_origin_y),
            grid_size=grid_size
        )
        
        # Initial position (x,y,0) - 2D position with z=0
        initial_position = np.array([0.0, 0.0, 0.0])
        self.position = initial_position
        self.position_cov = np.eye(3) * 0.1  # Initial covariance
        
        # Update rate
        self.dt = 0.1
        
        # Initialize Localization
        self.localization = Localization(
            initial_location=initial_position, 
            std_dev=position_std_dev,
            num_particles=num_particles,
            dt=self.dt
        )
        
        # Lidar range
        self.lidar_range = (0.1, 10.0)  # min and max range in meters
        
        # Current data
        self.lidar_data = []
        self.beacon_data = []
        self.control_input = np.zeros(3)  # vx, vy, 0

        # Subscribers
        self.create_subscription(
            PointCloud2, "/lidar", self.lidar_callback, 10
        )
        self.create_subscription(
            PointCloud2, "/beacon", self.beacon_callback, 10
        )
        self.create_subscription(
            Twist, "/cmd_vel", self.control_callback, 10
        )
        
        # Publishers
        self.pose_pub = self.create_publisher(PoseStamped, "/estimated_pose", 10)
        self.map_pub = self.create_publisher(OccupancyGrid, "/occupancy_grid", 10)
        self.beacon_pub = self.create_publisher(MarkerArray, "/estimated_beacons", 10)
        self.path_pub = self.create_publisher(Path, "/robot_path", 10)
        
        # Publisher for control commands (when using proposed control method)
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        
        # Timer for SLAM main loop
        self.create_timer(self.dt, self.slam_loop)
        
        # Path for visualization
        self.path = Path()
        self.path.header.frame_id = "map"
        
        self.get_logger().info("SLAM Node initialized")

    def lidar_callback(self, msg: PointCloud2):
        """Process LiDAR data"""
        try:
            points = list(read_points(msg, field_names=("x", "y", "z")))
            self.lidar_data = [np.array([p[0], p[1], p[2]]) for p in points]
        except Exception as e:
            self.get_logger().error(f"Error processing lidar data: {e}")

    def beacon_callback(self, msg: PointCloud2):
        """Process beacon data"""
        try:
            points = list(read_points(msg, field_names=("x", "y", "z")))
            self.beacon_data = [np.array([p[0], p[1], p[2]]) for p in points]
        except Exception as e:
            self.get_logger().error(f"Error processing beacon data: {e}")

    def control_callback(self, msg: Twist):
        """Process control input"""
        self.control_input = np.array([msg.linear.x, msg.linear.y, msg.linear.z])

    def slam_loop(self):
        """Main SLAM loop"""
        try:
            # Localization
            updated_position, updated_cov = self.localization.update_position(
                self.control_input,
                self.beacon_data,
                self.map
            )
            
            # Always set the orientation (theta) to 0 for 2D robot
            updated_position[2] = 0.0
            self.position = updated_position
            self.position_cov = np.diag([updated_cov[0], updated_cov[1], 0.0])  # Zero variance for theta
            
            # Mapping
            self.map.update(
                robot_pos=self.position,
                robot_cov=self.position_cov,
                lidar_data=self.lidar_data,
                lidar_range=self.lidar_range,
                beacon_data=self.beacon_data
            )
            
            # Visualization
            self.publish_pose()
            self.publish_map()
            self.publish_beacons()
            self.publish_path()
            
            # Control update based on selected method
            if self.use_proposed_control:
                self.update_control_proposed()
            else:
                # Using existing teleop code (no changes needed as it comes from /cmd_vel)
                pass
                
        except Exception as e:
            self.get_logger().error(f"Error in SLAM loop: {e}")

    def update_control_proposed(self):
        """Proposed control method: optimize towards finding beacons based on current map and position"""
        # If no beacon data is available, explore randomly
        if len(self.map.beacon_positions) == 0:
            # Random exploration if no beacons detected yet
            angular_z = 0.2  # slow rotation
            linear_x = 0.1   # slow forward movement
            cmd = Twist()
            cmd.linear.x = linear_x
            cmd.angular.z = angular_z
            self.cmd_vel_pub.publish(cmd)
            return
            
        # Find the beacon with highest uncertainty (largest covariance determinant)
        beacon_uncertainties = [np.linalg.det(cov) for cov in self.map.beacon_covariances]
        target_idx = np.argmax(beacon_uncertainties)
        target_beacon = self.map.beacon_positions[target_idx]
        
        # Calculate vector from robot to target beacon (2D only, ignore orientation)
        delta_x = target_beacon[0] - self.position[0]
        delta_y = target_beacon[1] - self.position[1]
        distance = math.sqrt(delta_x**2 + delta_y**2)
        
        # For 2D robot without orientation, just move directly towards target
        # (we ignore orientation/theta since robot frame is aligned with world frame)
        
        # Simple proportional control for movement
        k_linear = 0.3
        linear_x = min(k_linear * distance, 0.2)
        
        # Direction control (choose positive or negative x based on target direction)
        if delta_x < 0:
            linear_x = -linear_x
            
        # Create and publish control command
        cmd = Twist()
        cmd.linear.x = linear_x
        cmd.linear.y = 0.0  # No sideways movement
        cmd.angular.z = 0.0  # No rotation for 2D robot
        self.cmd_vel_pub.publish(cmd)

    def publish_pose(self):
        """Publish the estimated pose"""
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        
        # Position (2D)
        msg.pose.position.x = self.position[0]
        msg.pose.position.y = self.position[1]
        msg.pose.position.z = 0.0
        
        # Orientation - identity quaternion for 2D robot aligned with world frame
        msg.pose.orientation.x = 0.0
        msg.pose.orientation.y = 0.0
        msg.pose.orientation.z = 0.0
        msg.pose.orientation.w = 1.0  # Identity quaternion
        
        self.pose_pub.publish(msg)
        
        # Add to path for visualization
        self.path.header.stamp = self.get_clock().now().to_msg()
        self.path.poses.append(msg)
        if len(self.path.poses) > 1000:  # Limit path length
            self.path.poses.pop(0)

    def publish_map(self):
        """Publish occupancy grid"""
        msg = OccupancyGrid()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        
        # Map metadata
        msg.info.resolution = self.map.grid_size
        msg.info.width = self.map.log_odds_grid.shape[0]
        msg.info.height = self.map.log_odds_grid.shape[1]
        msg.info.origin.position.x = self.map.map_origin[0]
        msg.info.origin.position.y = self.map.map_origin[1]
        
        # Convert log-odds to probabilities and then to occupancy values [0, 100]
        grid_prob = np.zeros_like(self.map.log_odds_grid)
        for i in range(grid_prob.shape[0]):
            for j in range(grid_prob.shape[1]):
                log_odds = self.map.log_odds_grid[i, j]
                prob = 1.0 / (1.0 + np.exp(-log_odds))
                grid_prob[i, j] = int(prob * 100)
                
        # Flatten and convert to int8
        msg.data = grid_prob.flatten().astype(np.int8).tolist()
        self.map_pub.publish(msg)

    def publish_beacons(self):
        """Publish estimated beacon positions"""
        marker_array = MarkerArray()
        
        for i, (beacon_pos, beacon_cov) in enumerate(zip(self.map.beacon_positions, self.map.beacon_covariances)):
            marker = Marker()
            marker.header.frame_id = "map"
            marker.header.stamp = self.get_clock().now().to_msg()
            marker.ns = "beacons"
            marker.id = i
            marker.type = Marker.SPHERE
            marker.action = Marker.ADD
            
            # Position
            marker.pose.position.x = beacon_pos[0]
            marker.pose.position.y = beacon_pos[1]
            marker.pose.position.z = 0.0
            
            # Scale based on uncertainty
            uncertainty = np.sqrt(np.linalg.det(beacon_cov))
            scale = max(0.1, min(1.0, uncertainty))
            marker.scale.x = scale
            marker.scale.y = scale
            marker.scale.z = scale
            
            # Color (red, becoming more transparent with higher certainty)
            marker.color.r = 1.0
            marker.color.g = 0.0
            marker.color.b = 0.0
            marker.color.a = max(0.1, min(1.0, 1.0 - 0.9 * (1.0 - uncertainty)))
            
            marker_array.markers.append(marker)
            
        self.beacon_pub.publish(marker_array)

    def publish_path(self):
        """Publish robot path"""
        self.path_pub.publish(self.path)

def main(args=None):
    rclpy.init(args=args)
    node = SLAMNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()