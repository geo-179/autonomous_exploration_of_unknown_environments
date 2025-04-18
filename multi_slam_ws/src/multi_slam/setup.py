from setuptools import find_packages, setup
from glob import glob

package_name = 'multi_slam'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
        ('share/' + package_name + '/rviz', glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='gavin',
    maintainer_email='gavin.hyl@outlook.com',
    description='TODO: Package description',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 'visualization = multi_slam.visualization:main'
            'planner_slam_node = multi_slam.PlannerSlamNode:main',
            'planner_controller_node = multi_slam.PlannerControllerNode:main',
            'physics_sim = multi_slam.PhysicsSimNode:main',
            'controller_node = multi_slam.ControllerNode:main',
            'teleop_keyboard = multi_slam.teleop_keyboard:main',
            'slam_node = multi_slam.SlamNode:main',
        ],
    },
)