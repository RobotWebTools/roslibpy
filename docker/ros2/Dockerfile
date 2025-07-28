FROM ros:jazzy
LABEL maintainer="Gonzalo Casas <casas@arch.ethz.ch>"

SHELL ["/bin/bash","-c"]

# Install rosbridge
RUN apt-get update && apt-get install -y \
    ros-${ROS_DISTRO}-rosbridge-suite \
    # ros-${ROS_DISTRO}-tf2-web-republisher \
    # ros-${ROS_DISTRO}-ros-tutorials \
    # ros-${ROS_DISTRO}-actionlib-tutorials \
    --no-install-recommends \
    # Clear apt-cache to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Copy launch
COPY ./integration-tests.launch /

EXPOSE 9090

CMD ["bash"]
