from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import pygame

try:
    import obd  # type: ignore
except Exception:
    obd = None


APP_WIDTH = 1280
APP_HEIGHT = 480
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 720

WIDTH = APP_WIDTH
HEIGHT = APP_HEIGHT
FPS = 60

BG = (4, 6, 10)
WHITE = (245, 247, 250)
SOFT = (180, 186, 196)
DIM = (95, 104, 118)
RED = (255, 58, 58)
RED_DARK = (180, 18, 18)
AMBER = (255, 186, 70)
GREEN = (120, 255, 150)
BLUE = (100, 170, 255)
ROAD = (165, 170, 180)

SHIFT_GREEN = (90, 255, 120)
SHIFT_AMBER = (255, 190, 60)
SHIFT_RED = (255, 60, 60)
SHIFT_OFF = (28, 28, 32)

SHIFT_RPM_STAGE_1 = 400
SHIFT_RPM_STAGE_2 = 3000
SHIFT_RPM_STAGE_3 = 5500

START_ODOMETER_MI = 72485.0
ODOMETER_SAVE_FILE = Path(__file__).resolve().parent / "odometer.txt"

ASSET_DIR = Path(__file__).resolve().parent / "assets"

LEFT_DIAL_CENTER = (235, 235)
RIGHT_DIAL_CENTER = (1045, 235)
LEFT_DIAL_SIZE = 440
RIGHT_DIAL_SIZE = 440
LEFT_NEEDLE_SCALE = 0.34
RIGHT_NEEDLE_SCALE = 0.34
LEFT_NEEDLE_PIVOT = (0.18, 0.50)
RIGHT_NEEDLE_PIVOT = (0.82, 0.50)
LEFT_NEEDLE_BASE_ANGLE = 225.0
RIGHT_NEEDLE_BASE_ANGLE = 135.0
LEFT_NEEDLE_MIN_ANGLE = 123.0
LEFT_NEEDLE_MAX_ANGLE = 320.5
RIGHT_NEEDLE_MIN_ANGLE = 61.0
RIGHT_NEEDLE_MAX_ANGLE = -119.3


@dataclass
class CarData:
    speed_mph: float = 0.0
    rpm: float = 0.0
    coolant_c: Optional[float] = None
    fuel_pct: Optional[float] = None
    intake_c: Optional[float] = None
    voltage: Optional[float] = None
    odometer_mi: Optional[float] = None
    est_hp: Optional[float] = None
    inst_mpg: Optional[float] = None
    connected: bool = False
    source: str = "demo"


class OBDReader:
    def __init__(self) -> None:
        self.connection = None
        self.enabled = False
        self.last_attempt = 0.0
        self.retry_seconds = 5.0

        self.slow_counter = 0
        self.cached_coolant = None
        self.cached_fuel = None
        self.cached_intake = None
        self.cached_voltage = None
        self.cached_map = None

    def connect(self) -> None:
        if obd is None:
            return
        now = time.time()
        if now - self.last_attempt < self.retry_seconds:
            return
        self.last_attempt = now
        try:
            self.connection = obd.OBD("/dev/cu.usbserial-A77IPOSO", fast=True)
            self.enabled = self.connection is not None and self.connection.is_connected()
        except Exception:
            self.connection = None
            self.enabled = False

    def _query_value(self, command):
        if not self.connection:
            return None
        try:
            response = self.connection.query(command, force=True)
            if response is None or response.is_null():
                return None
            return response.value
        except Exception:
            return None

    def read(self) -> CarData:
        if not self.enabled:
            self.connect()
        if not self.enabled or not self.connection:
            return CarData(connected=False, source="demo")

        data = CarData(connected=True, source="obd")

        speed = self._query_value(obd.commands.SPEED)
        rpm = self._query_value(obd.commands.RPM)

        self.slow_counter += 1
        if self.slow_counter >= 5:
            self.slow_counter = 0
            self.cached_coolant = self._query_value(obd.commands.COOLANT_TEMP)
            self.cached_fuel = self._query_value(obd.commands.FUEL_LEVEL)
            self.cached_intake = self._query_value(obd.commands.INTAKE_TEMP)
            self.cached_voltage = self._query_value(obd.commands.ELM_VOLTAGE)
            self.cached_map = self._query_value(obd.commands.INTAKE_PRESSURE)

        coolant = self.cached_coolant
        fuel = self.cached_fuel
        intake = self.cached_intake
        voltage = self.cached_voltage
        map_pressure = self.cached_map

        try:
            data.speed_mph = float(speed.to("mph").magnitude) if speed is not None else 0.0
        except Exception:
            data.speed_mph = 0.0

        try:
            data.rpm = float(rpm.magnitude) if rpm is not None else 0.0
        except Exception:
            data.rpm = 0.0

        try:
            data.coolant_c = float(coolant.to("degC").magnitude) if coolant is not None else None
        except Exception:
            data.coolant_c = None

        try:
            data.fuel_pct = float(fuel.magnitude) if fuel is not None else None
        except Exception:
            data.fuel_pct = None

        try:
            data.intake_c = float(intake.to("degC").magnitude) if intake is not None else None
        except Exception:
            data.intake_c = None

        try:
            data.voltage = float(voltage.magnitude) if voltage is not None else None
        except Exception:
            data.voltage = None

        data.odometer_mi = None

        try:
            engine_displacement_l = 1.4
            volumetric_efficiency = 0.82

            if map_pressure is not None and data.intake_c is not None and data.rpm > 0:
                map_kpa = float(map_pressure.magnitude)
                intake_k = data.intake_c + 273.15
                airflow_index = (
                    map_kpa
                    * data.rpm
                    * engine_displacement_l
                    * volumetric_efficiency
                ) / intake_k
                data.est_hp = max(0.0, airflow_index * 3.2)
            else:
                data.est_hp = None
        except Exception:
            data.est_hp = None

        try:
            if data.est_hp is not None and data.est_hp > 1.0 and data.speed_mph > 1.0:
                fuel_gph = data.est_hp / 6.17
                data.inst_mpg = data.speed_mph / fuel_gph if fuel_gph > 0 else None
                if data.inst_mpg is not None:
                    data.inst_mpg = max(0.0, min(99.9, data.inst_mpg))
            else:
                data.inst_mpg = None
        except Exception:
            data.inst_mpg = None

        return data


class DemoDataSource:
    def __init__(self) -> None:
        self.t = 0.0
        self.manual_speed = 0.0
        self.manual_rpm = 900.0
        self.manual = False

    def update_manual(self, speed_delta: float = 0.0, rpm_delta: float = 0.0) -> None:
        self.manual = True
        self.manual_speed = max(0.0, min(160.0, self.manual_speed + speed_delta))
        self.manual_rpm = max(700.0, min(8000.0, self.manual_rpm + rpm_delta))

    def auto_tick(self, dt: float) -> CarData:
        self.t += dt
        if self.manual:
            speed = self.manual_speed
            rpm = self.manual_rpm
        else:
            speed = 45 + 30 * math.sin(self.t * 0.6) + 10 * math.sin(self.t * 1.4)
            speed = max(0.0, min(160.0, speed))
            rpm = 1200 + speed * 38 + 450 * math.sin(self.t * 1.2)
            rpm = max(850.0, min(8000.0, rpm))

        coolant = 92 + 4 * math.sin(self.t * 0.15)
        fuel = 63 - (self.t * 0.03) % 60
        intake = 30 + 3 * math.sin(self.t * 0.3)
        voltage = 13.8 + 0.12 * math.sin(self.t * 0.5)
        est_hp = max(0.0, min(170.0, (rpm / 8000.0) * 155.0 * (0.35 + speed / 160.0)))

        fuel_gph = est_hp / 6.17 if est_hp > 1.0 else 0.0
        inst_mpg = speed / fuel_gph if fuel_gph > 0 and speed > 1.0 else None
        if inst_mpg is not None:
            inst_mpg = max(0.0, min(99.9, inst_mpg))

        return CarData(
            speed_mph=speed,
            rpm=rpm,
            coolant_c=coolant,
            fuel_pct=max(0.0, fuel),
            intake_c=intake,
            voltage=voltage,
            odometer_mi=None,
            est_hp=est_hp,
            inst_mpg=inst_mpg,
            connected=False,
            source="demo",
        )


class DashApp:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Giulietta Digital Dash")
        self.display = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT), pygame.FULLSCREEN)
        self.screen = pygame.Surface((WIDTH, HEIGHT)).convert_alpha()
        self.clock = pygame.time.Clock()

        self.display_speed = 0.0
        self.raw_rpm_live = 0.0
        self.display_rpm = 0.0
        self.raw_rpm_filtered = 0.0

        self.rpm_input_alpha_up = 0.90
        self.rpm_input_alpha_down = 0.18
        self.rpm_follow_rate_up = 14000.0
        self.rpm_follow_rate_down = 4200.0
        self.rpm_snap_small_error = 8.0

        self.virtual_odometer_mi = self.load_virtual_odometer()
        self.last_odometer_save_time = time.time()
        self.odometer_save_interval = 5.0

        self.font_speed = pygame.font.SysFont("dejavusans", 68, bold=True)
        self.font_mph = pygame.font.SysFont("dejavusans", 22, bold=True)
        self.font_tick = pygame.font.SysFont("dejavusans", 18, bold=True)
        self.font_verybig = pygame.font.SysFont("dejavusans", 38, bold=True)
        self.font_big = pygame.font.SysFont("dejavusans", 24, bold=True)
        self.font_mid = pygame.font.SysFont("dejavusans", 18, bold=True)
        self.font_small = pygame.font.SysFont("dejavusans", 14, bold=True)
        self.font_tiny = pygame.font.SysFont("dejavusans", 12, bold=True)
        self.font_shift = pygame.font.SysFont("dejavusans", 28, bold=True)

        self.obd_reader = OBDReader()
        self.demo = DemoDataSource()
        self.use_demo = False
        self.last_data = CarData()
        self.last_read_time = 0.0
        self.read_interval = 0.01

        self.assets = self.load_assets()
        self.asset_status = self.describe_assets()

        self.pre_scaled_assets: Dict[str, pygame.Surface] = {}
        self.prepare_scaled_assets()

        self.show_startup = True
        self.startup_started_at = time.time()
        self.startup_min_time = 1.8

        self.show_intro = False
        self.intro_started_at = 0.0
        self.intro_duration = 0.7

        self.show_sweep = False
        self.sweep_started_at = 0.0
        self.sweep_duration = 1.6

    def load_virtual_odometer(self) -> float:
        try:
            if ODOMETER_SAVE_FILE.exists():
                value = float(ODOMETER_SAVE_FILE.read_text().strip())
                return max(0.0, value)
        except Exception:
            pass
        return START_ODOMETER_MI

    def save_virtual_odometer(self) -> None:
        try:
            ODOMETER_SAVE_FILE.write_text(f"{self.virtual_odometer_mi:.6f}")
        except Exception:
            pass

    def present_canvas_centered(self) -> None:
        scale = min(DISPLAY_WIDTH / WIDTH, DISPLAY_HEIGHT / HEIGHT)
        draw_w = max(1, int(WIDTH * scale))
        draw_h = max(1, int(HEIGHT * scale))
        scaled = pygame.transform.smoothscale(self.screen, (draw_w, draw_h))

        x = (DISPLAY_WIDTH - draw_w) // 2
        y = (DISPLAY_HEIGHT - draw_h) // 2

        self.display.fill((0, 0, 0))
        self.display.blit(scaled, (x, y))

    def update_rpm_display(self, raw_rpm: float, dt: float) -> float:
        self.raw_rpm_live = raw_rpm

        if self.raw_rpm_filtered <= 0.0:
            self.raw_rpm_filtered = raw_rpm
            self.display_rpm = raw_rpm
            return self.display_rpm

        alpha = self.rpm_input_alpha_up if raw_rpm >= self.raw_rpm_filtered else self.rpm_input_alpha_down
        self.raw_rpm_filtered += (raw_rpm - self.raw_rpm_filtered) * alpha

        rpm_error = self.raw_rpm_filtered - self.display_rpm

        if rpm_error > 0.0:
            max_step = self.rpm_follow_rate_up * dt
            self.display_rpm += min(rpm_error, max_step)
        elif rpm_error < 0.0:
            max_step = self.rpm_follow_rate_down * dt
            self.display_rpm -= min(abs(rpm_error), max_step)
            self.display_rpm += (self.raw_rpm_filtered - self.display_rpm) * min(1.0, dt * 3.5)

        if abs(self.raw_rpm_filtered - self.display_rpm) < self.rpm_snap_small_error:
            self.display_rpm = self.raw_rpm_filtered

        return self.display_rpm

    def draw_startup_screen(self) -> None:
        self.screen.fill((0, 0, 0))

        bg = self.pre_scaled_assets.get("startup_image")
        if bg is not None:
            bg_rect = bg.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 10))
            self.screen.blit(bg, bg_rect)
        else:
            title = self.font_speed.render("ALFA ROMEO", True, WHITE)
            title_rect = title.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 20))
            self.screen.blit(title, title_rect)

        dots = "." * (int((time.time() - self.startup_started_at) * 2.5) % 4)
        status = self.font_mid.render(dots, True, SOFT)
        status_rect = status.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 150))
        self.screen.blit(status, status_rect)

    def draw_intro_frame(self, t: float, live_data: CarData) -> None:
        eased = 1.0 - (1.0 - t) * (1.0 - t)
        scale = 0.88 + 0.12 * eased
        alpha = int(255 * eased)

        self.draw_background()
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

        left_dial = self.pre_scaled_assets.get("left_dial")
        right_dial = self.pre_scaled_assets.get("right_dial")

        speed = self.font_speed.render(str(int(round(0))), True, WHITE)
        mph = self.font_mph.render("MPH", True, WHITE)
        odo = self.font_mid.render(self.format_mileage(live_data.odometer_mi), True, SOFT)

        def blit_scaled_centered(surface: pygame.Surface, center: tuple[int, int]) -> None:
            w = max(1, int(surface.get_width() * scale))
            h = max(1, int(surface.get_height() * scale))
            scaled = pygame.transform.smoothscale(surface, (w, h)).copy()
            scaled.set_alpha(alpha)
            rect = scaled.get_rect(center=center)
            overlay.blit(scaled, rect)

        if left_dial is not None:
            blit_scaled_centered(left_dial, LEFT_DIAL_CENTER)

        if right_dial is not None:
            blit_scaled_centered(right_dial, RIGHT_DIAL_CENTER)

        blit_scaled_centered(speed, (WIDTH // 2, 200))
        blit_scaled_centered(mph, (WIDTH // 2, 120))
        blit_scaled_centered(odo, (WIDTH // 2, 370))

        self.screen.blit(overlay, (0, 0))
        self.draw_footer(live_data)

    def draw_sweep_frame(self, t: float, live_data: CarData) -> None:
        if t < 0.5:
            phase = t / 0.5
        else:
            phase = 1.0 - ((t - 0.5) / 0.5)

        phase = phase * phase * (3.0 - 2.0 * phase)

        sweep_speed = 160.0 * phase
        sweep_rpm = 8000.0 * phase

        draw_data = CarData(
            speed_mph=sweep_speed,
            rpm=sweep_rpm,
            coolant_c=live_data.coolant_c,
            fuel_pct=live_data.fuel_pct,
            intake_c=live_data.intake_c,
            voltage=live_data.voltage,
            odometer_mi=live_data.odometer_mi,
            est_hp=live_data.est_hp,
            inst_mpg=live_data.inst_mpg,
            connected=live_data.connected,
            source=live_data.source,
        )

        self.draw(draw_data, use_live_smoothed=False)

    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_F11:
                        pygame.display.toggle_fullscreen()
                    elif event.key == pygame.K_d:
                        self.use_demo = not self.use_demo
                        self.show_startup = False
                        self.show_intro = True
                        self.intro_started_at = time.time()
                        self.show_sweep = False
                    elif event.key == pygame.K_UP:
                        self.demo.update_manual(speed_delta=2, rpm_delta=180)
                    elif event.key == pygame.K_DOWN:
                        self.demo.update_manual(speed_delta=-2, rpm_delta=-180)
                    elif event.key == pygame.K_RIGHT:
                        self.demo.update_manual(speed_delta=5, rpm_delta=300)
                    elif event.key == pygame.K_LEFT:
                        self.demo.update_manual(speed_delta=-5, rpm_delta=-300)

            now = time.time()
            if self.use_demo:
                self.last_data = self.demo.auto_tick(dt)
            elif now - self.last_read_time >= self.read_interval:
                self.last_read_time = now
                obd_data = self.obd_reader.read()
                if obd_data.connected:
                    self.last_data = obd_data
                else:
                    self.last_data = self.demo.auto_tick(dt)
                    self.last_data.source = "demo"

            if not self.use_demo:
                distance_delta_mi = max(0.0, self.last_data.speed_mph) * dt / 3600.0
                self.virtual_odometer_mi += distance_delta_mi

                now_save = time.time()
                if now_save - self.last_odometer_save_time >= self.odometer_save_interval:
                    self.save_virtual_odometer()
                    self.last_odometer_save_time = now_save

            self.last_data.odometer_mi = self.virtual_odometer_mi

            speed_smooth = min(1.0, dt * 18.0)
            self.display_speed += (self.last_data.speed_mph - self.display_speed) * speed_smooth
            self.update_rpm_display(self.last_data.rpm, dt)

            if self.show_startup:
                min_time_done = (time.time() - self.startup_started_at) >= self.startup_min_time
                if min_time_done:
                    self.show_startup = False
                    self.show_intro = True
                    self.intro_started_at = time.time()
                else:
                    self.draw_startup_screen()
                    self.present_canvas_centered()
                    pygame.display.flip()
                    continue

            if self.show_intro:
                elapsed = time.time() - self.intro_started_at
                if elapsed >= self.intro_duration:
                    self.show_intro = False
                    self.show_sweep = True
                    self.sweep_started_at = time.time()
                else:
                    self.draw_intro_frame(elapsed / self.intro_duration, self.last_data)
                    self.present_canvas_centered()
                    pygame.display.flip()
                    continue

            if self.show_sweep:
                elapsed = time.time() - self.sweep_started_at
                if elapsed >= self.sweep_duration:
                    self.show_sweep = False
                else:
                    self.draw_sweep_frame(elapsed / self.sweep_duration, self.last_data)
                    self.present_canvas_centered()
                    pygame.display.flip()
                    continue

            self.draw(self.last_data)
            self.present_canvas_centered()
            pygame.display.flip()

        self.save_virtual_odometer()
        pygame.quit()
        sys.exit(0)

    def load_assets(self) -> Dict[str, Optional[pygame.Surface]]:
        files = {
            "background_image": "alfa_logo_faded.jpg",
            "startup_image": "boot_up.png",
            "left_dial": "left_speedometer_dial.png",
            "right_dial": "right_rpm_dial.png",
            "left_needle": "left_needle.png",
            "right_needle": "right_needle.png",
            "center_bg": "center_panel.png",
            "bezel": "overlay_bezel.png",
        }
        loaded: Dict[str, Optional[pygame.Surface]] = {}
        ASSET_DIR.mkdir(exist_ok=True)
        for key, filename in files.items():
            path = ASSET_DIR / filename
            if path.exists():
                try:
                    loaded[key] = pygame.image.load(str(path)).convert_alpha()
                except Exception:
                    loaded[key] = None
            else:
                loaded[key] = None
        return loaded

    def describe_assets(self) -> str:
        loaded_names = [key for key, surf in self.assets.items() if surf is not None]
        if not loaded_names:
            return "No image assets loaded"
        return "Assets: " + ", ".join(sorted(loaded_names))

    def prepare_scaled_assets(self) -> None:
        if self.assets.get("background_image") is not None:
            self.pre_scaled_assets["background_image"] = pygame.transform.smoothscale(
                self.assets["background_image"], (WIDTH, HEIGHT)
            )
        if self.assets.get("startup_image") is not None:
            startup = self.assets["startup_image"]
            target_w = WIDTH - 140
            scale = target_w / startup.get_width()
            target_h = max(1, int(startup.get_height() * scale))
            self.pre_scaled_assets["startup_image"] = pygame.transform.smoothscale(
                startup, (target_w, target_h)
            )

        if self.assets.get("left_dial") is not None:
            self.pre_scaled_assets["left_dial"] = pygame.transform.smoothscale(
                self.assets["left_dial"], (LEFT_DIAL_SIZE, LEFT_DIAL_SIZE)
            )

        if self.assets.get("right_dial") is not None:
            self.pre_scaled_assets["right_dial"] = pygame.transform.smoothscale(
                self.assets["right_dial"], (RIGHT_DIAL_SIZE, RIGHT_DIAL_SIZE)
            )

        if self.assets.get("bezel") is not None:
            self.pre_scaled_assets["bezel"] = pygame.transform.smoothscale(
                self.assets["bezel"], (WIDTH, HEIGHT)
            )

        if self.assets.get("left_needle") is not None:
            surf = self.assets["left_needle"]
            self.pre_scaled_assets["left_needle"] = pygame.transform.smoothscale(
                surf,
                (
                    max(1, int(surf.get_width() * LEFT_NEEDLE_SCALE)),
                    max(1, int(surf.get_height() * LEFT_NEEDLE_SCALE)),
                ),
            )

        if self.assets.get("right_needle") is not None:
            surf = self.assets["right_needle"]
            self.pre_scaled_assets["right_needle"] = pygame.transform.smoothscale(
                surf,
                (
                    max(1, int(surf.get_width() * RIGHT_NEEDLE_SCALE)),
                    max(1, int(surf.get_height() * RIGHT_NEEDLE_SCALE)),
                ),
            )

    def draw(self, data: CarData, use_live_smoothed: bool = True) -> None:
        draw_data = CarData(
            speed_mph=self.display_speed if use_live_smoothed else data.speed_mph,
            rpm=self.display_rpm if use_live_smoothed else data.rpm,
            coolant_c=data.coolant_c,
            fuel_pct=data.fuel_pct,
            intake_c=data.intake_c,
            voltage=data.voltage,
            odometer_mi=data.odometer_mi,
            est_hp=data.est_hp,
            inst_mpg=data.inst_mpg,
            connected=data.connected,
            source=data.source,
        )
        self.draw_background()
        self.draw_left_gauge(draw_data)
        self.draw_right_gauge(draw_data)
        self.draw_shift_alert(draw_data)
        self.draw_top_strip(draw_data)
        self.draw_bottom_cards(draw_data)
        self.draw_center_speed(draw_data)
        self.draw_footer(draw_data)
        self.draw_optional_overlay()

    def draw_background(self) -> None:
        bg = self.pre_scaled_assets.get("background_image")
        if bg is not None:
            self.screen.blit(bg, (0, 0))
        else:
            self.screen.fill(BG)
            for i in range(HEIGHT):
                shade = int(10 + 8 * (1 - i / HEIGHT))
                pygame.draw.line(self.screen, (0, 0, shade), (0, i), (WIDTH, i))

    def draw_top_strip(self, data: CarData) -> None:
        ambient = self.font_big.render(self.format_temp_f(data.intake_c), True, WHITE)
        self.screen.blit(ambient, (1200, 60))

    def draw_center_speed(self, data: CarData) -> None:
        speed = self.font_speed.render(str(int(round(data.speed_mph))), True, WHITE)
        mph = self.font_mph.render("MPH", True, WHITE)
        speed_rect = speed.get_rect(center=(WIDTH // 2, 200))
        mph_rect = mph.get_rect(midtop=(WIDTH // 2, 120))
        self.screen.blit(speed, speed_rect)
        self.screen.blit(mph, mph_rect)

        odo_value = self.font_mid.render(self.format_mileage(data.odometer_mi), True, SOFT)
        odo_value_rect = odo_value.get_rect(center=(WIDTH // 2, 370))
        self.screen.blit(odo_value, odo_value_rect)

    def draw_left_gauge(self, data: CarData) -> None:
        if self.pre_scaled_assets.get("left_dial") is not None:
            self.draw_dial_asset("left_dial", LEFT_DIAL_CENTER, LEFT_DIAL_SIZE)
        else:
            self.draw_speed_ring(LEFT_DIAL_CENTER, 170, 0, 160, data.speed_mph)
            self.draw_fuel_subgauge((190, 325), data.fuel_pct)

        if self.pre_scaled_assets.get("left_needle") is not None:
            angle = self.map_value_to_angle(
                data.speed_mph, 0.0, 160.0, LEFT_NEEDLE_MIN_ANGLE, LEFT_NEEDLE_MAX_ANGLE
            )
            self.draw_rotated_needle(
                "left_needle",
                LEFT_DIAL_CENTER,
                angle,
                LEFT_NEEDLE_BASE_ANGLE,
                LEFT_NEEDLE_SCALE,
                LEFT_NEEDLE_PIVOT,
            )
        else:
            self.draw_speed_needle(LEFT_DIAL_CENTER, 185, data.speed_mph, 160)

        fuel_range = int((data.fuel_pct or 0) * 6.8)
        rng = self.font_mid.render(str(fuel_range), True, WHITE)
        self.screen.blit(rng, (210, 338))
        self.screen.blit(self.font_small.render("mi", True, WHITE), (245, 340))

        hp_label = self.font_mid.render("HP", True, SOFT)
        hp_value = self.font_verybig.render(
            "--" if data.est_hp is None else str(int(round(data.est_hp))),
            True,
            WHITE,
        )

        hp_label_rect = hp_label.get_rect(center=(LEFT_DIAL_CENTER[0], LEFT_DIAL_CENTER[1] - 20))
        hp_value_rect = hp_value.get_rect(center=(LEFT_DIAL_CENTER[0], LEFT_DIAL_CENTER[1] + 8))

        self.screen.blit(hp_label, hp_label_rect)
        self.screen.blit(hp_value, hp_value_rect)

        mpg_label = self.font_tiny.render("CUR MPG", True, SOFT)
        mpg_value = self.font_mid.render(self.format_mpg(data.inst_mpg), True, WHITE)

        mpg_label_rect = mpg_label.get_rect(center=(LEFT_DIAL_CENTER[0], LEFT_DIAL_CENTER[1] + 42))
        mpg_value_rect = mpg_value.get_rect(center=(LEFT_DIAL_CENTER[0], LEFT_DIAL_CENTER[1] + 60))

        self.screen.blit(mpg_label, mpg_label_rect)
        self.screen.blit(mpg_value, mpg_value_rect)

    def draw_right_gauge(self, data: CarData) -> None:
        if self.pre_scaled_assets.get("right_dial") is not None:
            self.draw_dial_asset("right_dial", RIGHT_DIAL_CENTER, RIGHT_DIAL_SIZE)
        else:
            self.draw_rpm_ring(RIGHT_DIAL_CENTER, 170, 0, 8, data.rpm / 1000.0)
            self.draw_temp_subgauge((1090, 325), data.coolant_c)

        if self.pre_scaled_assets.get("right_needle") is not None:
            angle = self.map_value_to_angle(
                data.rpm, 0.0, 8000.0, RIGHT_NEEDLE_MIN_ANGLE, RIGHT_NEEDLE_MAX_ANGLE
            )
            self.draw_rotated_needle(
                "right_needle",
                RIGHT_DIAL_CENTER,
                angle,
                RIGHT_NEEDLE_BASE_ANGLE,
                RIGHT_NEEDLE_SCALE,
                RIGHT_NEEDLE_PIVOT,
            )
        else:
            self.draw_rpm_needle(RIGHT_DIAL_CENTER, 165, data.rpm / 1000.0, 8)

        rpm_digits = self.font_verybig.render(f"{int(round(data.rpm))}", True, WHITE)
        rpm_label = self.font_mid.render("RPM", True, SOFT)
        rpm_rect = rpm_digits.get_rect(center=(RIGHT_DIAL_CENTER[0], RIGHT_DIAL_CENTER[1] + 5))
        label_rect = rpm_label.get_rect(center=(RIGHT_DIAL_CENTER[0], RIGHT_DIAL_CENTER[1] - 20))
        self.screen.blit(rpm_digits, rpm_rect)
        self.screen.blit(rpm_label, label_rect)

        rpm_raw_small = self.font_tiny.render(f"RAW {int(round(self.raw_rpm_live))}", True, SOFT)
        rpm_raw_rect = rpm_raw_small.get_rect(center=(RIGHT_DIAL_CENTER[0], RIGHT_DIAL_CENTER[1] + 36))
        self.screen.blit(rpm_raw_small, rpm_raw_rect)

    def draw_shift_alert(self, data: CarData) -> None:
        rpm = data.rpm
        if rpm < 400:
            return

        alert_y = 50
        shape_w = 35
        shape_h = 50
        gap = 3

        left_start_x = 550
        right_start_x = 730

        flash_on = (pygame.time.get_ticks() // 180) % 2 == 0
        off_color = (35, 35, 35)

        left_colors = [off_color, off_color, off_color]
        right_colors = [off_color, off_color, off_color]
        text_color = (60, 60, 65)

        if 400 <= rpm < 3000:
            left_colors[2] = GREEN
            right_colors[2] = GREEN
        elif 3000 <= rpm < 5500:
            left_colors[1] = AMBER
            left_colors[2] = GREEN
            right_colors[1] = AMBER
            right_colors[2] = GREEN
        elif rpm >= 5500:
            left_colors[1] = AMBER
            left_colors[2] = GREEN
            right_colors[1] = AMBER
            right_colors[2] = GREEN
            if flash_on:
                left_colors[0] = RED
                right_colors[0] = RED
                text_color = WHITE

        for i in range(3):
            x = left_start_x - i * (shape_w + gap)
            self.draw_rhombus(x, alert_y, shape_w, shape_h, left_colors[i], flip=False)

        for i in range(3):
            x = right_start_x + i * (shape_w + gap)
            self.draw_rhombus(x, alert_y, shape_w, shape_h, right_colors[i], flip=True)

        shift_surf = self.font_big.render("SHIFT", True, text_color)
        shift_rect = shift_surf.get_rect(center=(WIDTH // 2, alert_y))
        self.screen.blit(shift_surf, shift_rect)

    def draw_rhombus(
        self,
        cx: int,
        cy: int,
        w: int,
        h: int,
        color: Tuple[int, int, int],
        flip: bool = False,
    ) -> None:
        skew = w // 4

        if not flip:
            points = [
                (cx - w // 2 - skew, cy - h // 2),
                (cx + w // 2 - skew, cy - h // 2),
                (cx + w // 2 + skew, cy + h // 2),
                (cx - w // 2 + skew, cy + h // 2),
            ]
        else:
            points = [
                (cx - w // 2 + skew, cy - h // 2),
                (cx + w // 2 + skew, cy - h // 2),
                (cx + w // 2 - skew, cy + h // 2),
                (cx - w // 2 - skew, cy + h // 2),
            ]

        pygame.draw.polygon(self.screen, color, points)

    def draw_bottom_cards(self, data: CarData) -> None:
        bar = pygame.Rect(350, 392, 600, 56)
        pygame.draw.rect(self.screen, (0, 0, 0), bar, border_radius=16)
        pygame.draw.rect(self.screen, (40, 44, 52), bar, 1, border_radius=16)

        cards = [
            ("COOLANT", self.format_temp_f(data.coolant_c), self.coolant_color(data.coolant_c), self.metric_ratio(0, data), ("C", "H")),
            ("FUEL", self.format_pct(data.fuel_pct), WHITE, self.metric_ratio(2, data), ("E", "F")),
            ("VOLTAGE", self.format_voltage(data.voltage), WHITE, self.metric_ratio(3, data), ("L", "H")),
        ]

        x = 380
        for label, value, color, ratio, caps in cards:
            self.draw_card(x, 401, label, value, color, ratio, caps)
            x += 200

    def draw_card(
        self,
        x: int,
        y: int,
        label: str,
        value: str,
        color,
        ratio: Optional[float],
        caps: Optional[Tuple[str, str]],
    ) -> None:
        self.screen.blit(self.font_tiny.render(label, True, WHITE), (x, y))
        self.screen.blit(self.font_small.render(value, True, color), (x, y + 12))
        if ratio is not None and caps is not None:
            bar_x, bar_y, bar_w, bar_h = x, y + 28, 86, 5
            pygame.draw.rect(self.screen, (70, 74, 82), (bar_x, bar_y, bar_w, bar_h), border_radius=4)
            fill = int(bar_w * ratio)
            if fill > 0:
                fill_color = RED if caps[1] == "H" and ratio > 0.82 else BLUE if label == "INTAKE" else WHITE
                pygame.draw.rect(self.screen, fill_color, (bar_x, bar_y, fill, bar_h), border_radius=4)
            self.screen.blit(self.font_tiny.render(caps[0], True, SOFT), (bar_x, bar_y + 7))
            self.screen.blit(self.font_tiny.render(caps[1], True, RED if caps[1] == "H" else SOFT), (bar_x + 78, bar_y + 7))

    def draw_footer(self, data: CarData) -> None:
        self.screen.blit(self.font_tiny.render(time.strftime("%I:%M %p").lstrip("0"), True, SOFT), (120, 456))
        status = "LIVE OBD" if data.connected and data.source == "obd" else "DEMO MODE"
        status_color = GREEN if status == "LIVE OBD" else AMBER
        msg = self.font_tiny.render(f"{status}  |  F11 fullscreen  |  D toggle mode", True, status_color)
        self.screen.blit(msg, (465, 456))
        self.screen.blit(self.font_tiny.render(time.strftime("%m/%d/%Y"), True, SOFT), (1085, 456))

    def draw_optional_overlay(self) -> None:
        bezel = self.pre_scaled_assets.get("bezel")
        if bezel is None:
            return
        self.screen.blit(bezel, (0, 0))

    def draw_dial_asset(self, key: str, center: Tuple[int, int], size: int) -> None:
        surf = self.pre_scaled_assets.get(key)
        if surf is None:
            return
        rect = surf.get_rect(center=center)
        self.screen.blit(surf, rect)

    def draw_rotated_needle(
        self,
        key: str,
        center: Tuple[int, int],
        angle: float,
        base_angle: float,
        scale: float,
        pivot_norm: Tuple[float, float],
    ) -> None:
        surf = self.pre_scaled_assets.get(key)
        if surf is None:
            return

        scaled_w = surf.get_width()
        scaled_h = surf.get_height()

        rotation = -(angle - base_angle)
        rotated = pygame.transform.rotate(surf, rotation)

        pivot_x = scaled_w * pivot_norm[0]
        pivot_y = scaled_h * pivot_norm[1]
        image_center = pygame.math.Vector2(scaled_w / 2, scaled_h / 2)
        pivot_vector = pygame.math.Vector2(pivot_x, pivot_y) - image_center
        rotated_offset = pivot_vector.rotate(rotation)

        draw_center = pygame.math.Vector2(center[0], center[1]) - rotated_offset
        rect = rotated.get_rect(center=(round(draw_center.x), round(draw_center.y)))
        self.screen.blit(rotated, rect)

    def draw_arc(
        self,
        center: Tuple[int, int],
        radius: int,
        start_deg: float,
        end_deg: float,
        color: Tuple[int, int, int],
        width: int,
    ) -> None:
        steps = max(20, int(abs(end_deg - start_deg) * 1.6))
        points = []
        for i in range(steps + 1):
            deg = start_deg + (end_deg - start_deg) * (i / steps)
            points.append(self.polar(center, radius, deg))
        pygame.draw.lines(self.screen, color, False, points, width)

    @staticmethod
    def polar(center: Tuple[int, int], radius: float, deg: float) -> Tuple[int, int]:
        rad = math.radians(deg)
        return int(center[0] + math.cos(rad) * radius), int(center[1] + math.sin(rad) * radius)

    @staticmethod
    def map_value_to_angle(value: float, min_value: float, max_value: float, start_angle: float, end_angle: float) -> float:
        if max_value <= min_value:
            return start_angle
        ratio = max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))
        return start_angle + (end_angle - start_angle) * ratio

    def draw_speed_ring(self, center: Tuple[int, int], radius: int, min_value: int, max_value: int, value: float) -> None:
        start_deg, end_deg = 138, 402
        self.draw_arc(center, radius, start_deg, end_deg, WHITE, 3)
        self.draw_arc(center, radius - 22, start_deg, end_deg, (180, 180, 184), 1)
        for i, tick in enumerate(range(min_value, max_value + 1, 10)):
            ratio = i / ((max_value - min_value) / 10)
            deg = start_deg + (end_deg - start_deg) * ratio
            outer = self.polar(center, radius - 2, deg)
            inner = self.polar(center, radius - 24, deg)
            pygame.draw.line(self.screen, WHITE, outer, inner, 3)
            if tick % 20 == 0:
                txt_pt = self.polar(center, radius - 52, deg)
                txt = self.font_tick.render(str(tick), True, WHITE)
                self.screen.blit(txt, txt.get_rect(center=txt_pt))
        self.screen.blit(self.font_mid.render("MPH", True, SOFT), (77, 285))

    def draw_rpm_ring(self, center: Tuple[int, int], radius: int, min_value: int, max_value: int, value: float) -> None:
        start_deg, end_deg = -42, 222
        self.draw_arc(center, radius, start_deg, end_deg, WHITE, 3)
        self.draw_arc(center, radius - 22, start_deg, end_deg, (180, 180, 184), 1)
        self.draw_arc(center, radius, -42, 42, RED_DARK, 14)
        for i, tick in enumerate(range(min_value, max_value + 1)):
            ratio = i / (max_value - min_value)
            deg = start_deg + (end_deg - start_deg) * ratio
            outer = self.polar(center, radius - 2, deg)
            inner = self.polar(center, radius - 24, deg)
            pygame.draw.line(self.screen, WHITE, outer, inner, 3)
            txt_pt = self.polar(center, radius - 52, deg)
            txt = self.font_big.render(str(tick), True, WHITE)
            self.screen.blit(txt, txt.get_rect(center=txt_pt))
        self.screen.blit(self.font_mid.render("RPM", True, WHITE), (1172, 285))
        self.screen.blit(self.font_tiny.render("x1000", True, SOFT), (1184, 303))

    def draw_speed_needle(self, center: Tuple[int, int], length: int, value: float, max_value: float) -> None:
        deg = self.map_value_to_angle(value, 0.0, max_value, LEFT_NEEDLE_MIN_ANGLE, LEFT_NEEDLE_MAX_ANGLE)
        self.draw_needle(center, length, deg)

    def draw_rpm_needle(self, center: Tuple[int, int], length: int, value: float, max_value: float) -> None:
        deg = self.map_value_to_angle(value, 0.0, max_value, RIGHT_NEEDLE_MIN_ANGLE, RIGHT_NEEDLE_MAX_ANGLE)
        self.draw_needle(center, length, deg)

    def draw_needle(self, center: Tuple[int, int], length: int, deg: float) -> None:
        start = self.polar(center, length * 0.55, deg)
        tip = self.polar(center, length, deg)
        pygame.draw.line(self.screen, RED, start, tip, 3)

    def draw_fuel_subgauge(self, center: Tuple[int, int], fuel_pct: Optional[float]) -> None:
        start_deg, end_deg = 205, 335
        radius = 72
        self.draw_arc(center, radius, start_deg, end_deg, (75, 78, 85), 8)
        ratio = 0.0 if fuel_pct is None else max(0.0, min(1.0, fuel_pct / 100.0))
        self.draw_arc(center, radius, start_deg, start_deg + (end_deg - start_deg) * ratio, WHITE, 8)
        self.draw_arc(center, radius, start_deg, start_deg + 18, RED, 8)
        self.screen.blit(self.font_small.render("E", True, RED), (126, 335))
        self.screen.blit(self.font_small.render("F", True, WHITE), (250, 335))

    def draw_temp_subgauge(self, center: Tuple[int, int], coolant_c: Optional[float]) -> None:
        start_deg, end_deg = 205, 335
        radius = 72
        self.draw_arc(center, radius, start_deg, end_deg, (75, 78, 85), 8)
        ratio = 0.0 if coolant_c is None else max(0.0, min(1.0, (coolant_c - 50) / 70.0))
        self.draw_arc(center, radius, start_deg, start_deg + (end_deg - start_deg) * ratio, WHITE, 8)
        self.draw_arc(center, radius, end_deg - 18, end_deg, RED, 8)
        self.screen.blit(self.font_small.render("C", True, WHITE), (1026, 335))
        self.screen.blit(self.font_small.render("H", True, RED), (1150, 335))

    @staticmethod
    def format_temp_f(value_c: Optional[float]) -> str:
        if value_c is None:
            return "--°C"
        return f"{int(round(value_c))}°C"

    @staticmethod
    def format_pct(value: Optional[float]) -> str:
        return "--%" if value is None else f"{int(round(value))}%"

    @staticmethod
    def format_voltage(value: Optional[float]) -> str:
        return "--.-V" if value is None else f"{value:.1f}V"

    @staticmethod
    def format_mpg(value: Optional[float]) -> str:
        if value is None:
            return "-- mpg"
        return f"{value:.1f} mpg"

    @staticmethod
    def coolant_color(value: Optional[float]) -> Tuple[int, int, int]:
        if value is None:
            return WHITE
        if value >= 112:
            return RED
        if value >= 103:
            return AMBER
        return WHITE

    @staticmethod
    def metric_ratio(index: int, data: CarData) -> float:
        if index == 0:
            return 0.0 if data.coolant_c is None else max(0.0, min(1.0, (data.coolant_c - 50) / 70.0))
        if index == 1:
            return 0.0 if data.intake_c is None else max(0.0, min(1.0, (data.intake_c + 10) / 60.0))
        if index == 2:
            return 0.0 if data.fuel_pct is None else max(0.0, min(1.0, data.fuel_pct / 100.0))
        return 0.0 if data.voltage is None else max(0.0, min(1.0, (data.voltage - 11.5) / 3.0))

    @staticmethod
    def format_mileage(value: Optional[float]) -> str:
        if value is None:
            return "-- mi"
        return f"{int(round(value))} mi"


if __name__ == "__main__":
    DashApp().run()