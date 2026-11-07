FROM rwthika/ros2:jazzy-desktop-full

RUN ln -snf /usr/share/zoneinfo/Europe/Madrid /etc/localtime && \
    echo Europe/Madrid > /etc/timezone
RUN wget -qO /usr/share/keyrings/xpra.asc https://xpra.org/xpra.asc && \
    echo "deb [signed-by=/usr/share/keyrings/xpra.asc] https://xpra.org/ $(lsb_release -cs) main"  > /etc/apt/sources.list.d/xpra.list
RUN apt update && \
    apt full-upgrade -y && \
    apt install -y \
        mesa-utils \
        iproute2 \
        strace \
        swig \
        telnet \
        tree \
        xfce4-terminal \
        xpra && \
    apt clean

# Paquetes de Python.
# scipy explícito: la versión de Ubuntu es demasiado antigua para robobopy.
ARG PIP_CACHEBUST=0
ARG TORCH_VARIANT=cpu
RUN echo "PIP_CACHEBUST=$PIP_CACHEBUST" && \
    pip install --user --upgrade --no-cache-dir \
        scipy \
        robobopy \
        robobopy_videostream && \
    if [ "$TORCH_VARIANT" = "cuda" ]; then \
        echo "Instalando PyTorch con CUDA" && \
        pip install --user --upgrade --no-cache-dir torch; \
    else \
        echo "Instalando PyTorch para CPU" && \
        pip install --user --upgrade --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch; \
    fi && \
    pip install --user --upgrade --no-cache-dir \
        "stable-baselines3[extra]" \
        "gymnasium[all]" \
        gymnasium-robotics \
        neat-python

# Paquetes ROS 2 del Robobo.
ARG ROBOBO_CACHEBUST=0
RUN echo "ROBOBO_CACHEBUST=$ROBOBO_CACHEBUST" && \
    git config --system http.version HTTP/1.1 && \
    git clone https://github.com/rodrigo-mintin/robobo_ros2.git && \
    cd robobo_ros2 && \
    git checkout c6b7b7c && \
    source /opt/ros/jazzy/setup.bash && \
    colcon build --merge-install --install-base /opt/ros/robobo && \
    cd .. && \
    rm -rf robobo_ros2 && \
    echo "source /opt/ros/robobo/setup.bash" >> /root/.bashrc
