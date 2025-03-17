from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import ExecuteProcess
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # Get the package share directory
    pkg_share = get_package_share_directory('multi_slam')
    
    # Create path to RViz config file
    rviz_config_path = os.path.join(pkg_share, 'rviz', 'config.rviz')
    
    # Get the absolute path to the script
    script_path = '/home/tkleeneuron/cs133b-final-project/multi_slam_ws/src/multi_slam/multi_slam/autonomous_control/info_thry_approach.py'
    
    return LaunchDescription([
        Node(
            package='multi_slam',
            executable='physics_sim',
            name='physics_sim',
            output='screen'
        ),
        # SLAM node for simultaneous localization and mapping
        Node(
            package='multi_slam',
            executable='slam_node',
            name='slam_node',
            output='screen',
        ),
        # Information-theoretic autonomous exploration controller
        ExecuteProcess(
            cmd=['python3', script_path,
                 '--ros-args',
                 '-p', 'exploration_radius:=2.0',
                 '-p', 'num_candidates:=8',
                 '-p', 'move_step:=0.5',
                 '-p', 'occupancy_threshold:=50',
                 '-p', 'unknown_weight:=1.0',
                 '-p', 'beacon_weight:=3.0',
                 '-p', 'beacon_proximity_threshold:=5.0',
            ],
            name='info_theoretic_controller',
            output='screen'
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config_path]
        )
    ]) 