from launch import LaunchDescription
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch.actions import ExecuteProcess, IncludeLaunchDescription

def generate_launch_description():
    return LaunchDescription([
        # Start rosbridge_websocket
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare('rosbridge_server'),
                'launch',
                'rosbridge_websocket_launch.xml'
            ])
        ),

        # Start fibonacci_server.py with python3
        ExecuteProcess(
            cmd=['python3', "/fibonacci_server.py"],
            output='screen'
        )
    ])
