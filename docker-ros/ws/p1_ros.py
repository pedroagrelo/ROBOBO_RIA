#!/usr/bin/env python3
"""
Práctica 1 — Capa de comunicación con ROS 2 (robot seguidor).

No se ejecuta directamente. Todo lo que habla con el nodo puente está
aquí, para que lo usen igual el entorno de Gymnasium (p1_follow_env.py) y
la calibración (p1_calibrar_colocar.py). Necesita el puente lanzado:

  ros2 run robobo_ros2 robobo_container --ros-args -p ip:=host.docker.internal -p modules:="['blob','sim']"

Dos canales:

  base/ y smartphone/  percepción (blobs, IR) y actuación (cmd_vel, tilt).
                       Es lo único que existe en el robot real y lo único
                       que entra en la observación.
  sim/                 reinicio de la escena y pose del seguidor (sólo
                       simulador). El guía es un objeto de RoboboSim, no
                       un robot: su pose se lee con robobosim en
                       p1_evaluar.py y p1_calibrar_colocar.py.

Unidades: la pose del seguidor se guarda en METROS (el módulo sim
publica milímetros).
"""

import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data

from std_msgs.msg import Int32MultiArray
from geometry_msgs.msg import Twist

from robobo_ros2_interfaces.msg import BlobArray, RobotLocation
from robobo_ros2_interfaces.srv import SetActiveColorBlobs, ResetSimulation
from robobo_ros2_interfaces.action import MoveTilt


class RoboboROS:
    """Acceso a sensores, actuadores y canal sim del seguidor."""

    def __init__(self, cfg, nombre_nodo='p1_robobo'):
        self.cfg = cfg

        if not rclpy.ok():
            rclpy.init()
        self.nodo = Node(nombre_nodo)

        seg = cfg['ros']['seguidor']
        self.ns_base = '/robobo/robot_{}/base'.format(seg)
        self.ns_phone = '/robobo/robot_{}/smartphone'.format(seg)
        self.ns_sim = '/robobo/robot_{}/sim'.format(seg)

        # ------------------------------------------------ actuación
        # El publicador se crea UNA vez (el descubrimiento tarda).
        self.pub_vel = self.nodo.create_publisher(Twist, self.ns_base + '/cmd_vel', 10)

        # ------------------------------------------------ blobs (5 Hz)
        # Es el sensor que marca el ritmo del bucle de control: cada
        # step() espera a un BlobArray nuevo. El detector publica también
        # la lista vacía, así que el contador avanza aunque no se vea nada.
        self.color = cfg['blob']['color'].lower()
        self.blob = None          # dict {x, y, size} del blob del color o None
        self.n_blobs = 0
        # QoS "sensor_data" (best effort): recibe tanto de publicadores
        # reliable como best effort; con reliable sólo se recibiría de los
        # reliable y un tópico podría aparecer en la lista pero a 0 Hz.
        qos = qos_profile_sensor_data
        self.nodo.create_subscription(
            BlobArray, self.ns_phone + '/color_blobs', self._cb_blobs, qos)

        # ------------------------------------------------ infrarrojos
        self.ir = None
        self.n_ir = 0
        if cfg['ir']['usar']:
            self.nodo.create_subscription(
                Int32MultiArray, self.ns_base + '/' + cfg['ir']['topic'],
                self._cb_ir, qos)

        # ------------------------------------------------ servicios/acciones
        self.cli_blobs = self.nodo.create_client(
            SetActiveColorBlobs, self.ns_phone + '/set_active_color_blobs')
        self.act_tilt = ActionClient(self.nodo, MoveTilt, self.ns_base + '/move_tilt')

        # ------------------------------------------------ canal sim
        self.pose_seg = None      # (x, z, yaw_grados) en m
        self.n_pose_seg = 0
        self.cli_reset = self.nodo.create_client(
            ResetSimulation, self.ns_sim + '/reset_simulation')
        self.nodo.create_subscription(
            RobotLocation, self.ns_sim + '/robot_location', self._cb_pose_seg, qos)

    # =================================================================
    # Callbacks (sólo se ejecutan dentro de spin_once)
    # =================================================================

    def _cb_blobs(self, msg):
        elegido = None
        for b in msg.blobs:
            if self.color in str(b.color).lower():
                elegido = {'x': float(b.x), 'y': float(b.y), 'size': float(b.size)}
                break
        self.blob = elegido
        self.n_blobs += 1

    def _cb_ir(self, msg):
        self.ir = list(msg.data)
        self.n_ir += 1

    @staticmethod
    def _pose_m(msg):
        return (msg.position.x / 1000.0, msg.position.z / 1000.0, float(msg.rotation.y))

    def _cb_pose_seg(self, msg):
        self.pose_seg = self._pose_m(msg)
        self.n_pose_seg += 1

    # =================================================================
    # Gestión del ejecutor
    # =================================================================

    def spin(self, segundos):
        """Procesa callbacks durante 'segundos'."""
        t_fin = time.time() + segundos
        while time.time() < t_fin:
            rclpy.spin_once(self.nodo, timeout_sec=0.02)

    def vaciar_cola(self):
        """Procesa todo lo pendiente sin bloquear.

        Deja actualizados blob, ir y pose_seg con lo último recibido.
        """
        for _ in range(200):
            antes = (self.n_blobs, self.n_ir, self.n_pose_seg)
            rclpy.spin_once(self.nodo, timeout_sec=0.0)
            if (self.n_blobs, self.n_ir, self.n_pose_seg) == antes:
                return

    def esperar_blob_nuevo(self, timeout=3.0, keepalive=None):
        """Bloquea hasta recibir un BlobArray POSTERIOR a esta llamada.

        Es la garantía de que la observación de step() corresponde a un
        instante posterior a la acción (requisito del apartado 5.2).

        keepalive=(v, w): mientras se espera, se reenvía la orden para
        que el watchdog de cmd_vel (0.5 s) no pare el robot.
        """
        objetivo = self.n_blobs + 1
        t0 = time.time()
        t_ka = t0
        ka = self.cfg['control']['keepalive_s']
        while self.n_blobs < objetivo:
            rclpy.spin_once(self.nodo, timeout_sec=0.02)
            ahora = time.time()
            if keepalive is not None and ahora - t_ka >= ka:
                self.publicar(*keepalive)
                t_ka = ahora
            if ahora - t0 > timeout:
                raise RuntimeError(
                    'No llegan mensajes de {}/color_blobs. ¿Está lanzado el '
                    'contenedor con el módulo blob?'.format(self.ns_phone))

    # =================================================================
    # Actuación
    # =================================================================

    def publicar(self, v, w):
        msg = Twist()
        msg.linear.x = float(v)
        msg.angular.z = float(w)
        self.pub_vel.publish(msg)

    def aplicar_durante(self, v, w, segundos):
        """Aplica (v, w) durante 'segundos', reenviando la orden (keepalive).

        No hace spin: lo que llegue mientras tanto se queda en cola y se
        procesa después con vaciar_cola().
        """
        ka = self.cfg['control']['keepalive_s']
        t_fin = time.time() + segundos
        while True:
            self.publicar(v, w)
            resto = t_fin - time.time()
            if resto <= 0:
                break
            time.sleep(min(ka, resto))

    def detener(self):
        for _ in range(3):
            self.publicar(0.0, 0.0)
            time.sleep(0.05)

    # =================================================================
    # Configuración de la cámara
    # =================================================================

    def _llamar(self, cliente, req, timeout=3.0):
        if not cliente.wait_for_service(timeout_sec=timeout):
            return None
        fut = cliente.call_async(req)
        rclpy.spin_until_future_complete(self.nodo, fut, timeout_sec=timeout)
        return fut.result() if fut.done() else None

    def activar_color(self):
        """Activa SÓLO la detección del color de la pelota."""
        req = SetActiveColorBlobs.Request()
        req.red = self.color == 'red'
        req.green = self.color == 'green'
        req.blue = self.color == 'blue'
        req.custom = False
        resp = self._llamar(self.cli_blobs, req)
        ok = bool(resp and resp.success)
        if not ok:
            self.nodo.get_logger().warning('No se pudo configurar set_active_color_blobs')
        return ok

    def mover_tilt(self, angulo, velocidad=10.0, timeout=20.0):
        """Mueve el tilt y espera a que termine (acción move_tilt)."""
        if not self.act_tilt.wait_for_server(timeout_sec=3.0):
            self.nodo.get_logger().warning('Acción move_tilt no disponible')
            return False
        goal = MoveTilt.Goal()
        goal.angle = float(angulo)
        goal.speed = float(velocidad)
        f = self.act_tilt.send_goal_async(goal)
        rclpy.spin_until_future_complete(self.nodo, f, timeout_sec=5.0)
        if not f.done() or not f.result() or not f.result().accepted:
            return False
        r = f.result().get_result_async()
        rclpy.spin_until_future_complete(self.nodo, r, timeout_sec=timeout)
        return bool(r.done() and r.result() and r.result().result.success)

    # =================================================================
    # Canal sim
    # =================================================================

    def reiniciar_escena(self):
        if not self.cli_reset.wait_for_service(timeout_sec=5.0):
            raise RuntimeError('No responde {}/reset_simulation (¿módulo sim?)'
                               .format(self.ns_sim))
        fut = self.cli_reset.call_async(ResetSimulation.Request())
        rclpy.spin_until_future_complete(self.nodo, fut, timeout_sec=5.0)
        if not fut.done() or fut.result() is None or not fut.result().success:
            raise RuntimeError('El reinicio de la escena ha fallado.')
        # La pose anterior ya no vale.
        self.pose_seg = None

    # =================================================================
    # Lecturas
    # =================================================================

    def ir_frontal_crudo(self):
        if self.ir is None:
            return 0
        return max(max(self.ir[i], 0) for i in self.cfg['ir']['indices_frontales'])

    def close(self):
        try:
            self.detener()
        except Exception:
            pass
        try:
            self.nodo.destroy_node()
        except Exception:
            pass
