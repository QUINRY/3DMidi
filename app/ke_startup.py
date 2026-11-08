"""Ender-3 V3 KE automatic homing and an isolated slow clearance move.

Homing uses the normal source-profile motion limits.  Only the subsequent
clearance move is slowed.  See the optional Z-only FORCE_MOVE wrapper.
"""
from __future__ import annotations

import math

KE_ID = "creality_ender3_v3_ke"
KE_AUTO_STARTUP = "ke_auto_home_slow_z"
CLEARANCE_Z_SPEED_MM_S = 3.0
CLEARANCE_Z_ACCEL_MM_S2 = 100.0
CLEARANCE_Z_MM = 20.0
SOURCE_COMMIT = "a63fb1a71672b91b505e0bda68fae2ede49f1168"
SOURCE_BASE = f"https://github.com/CrealityOfficial/Ender-3_V3_KE_Klipper/blob/{SOURCE_COMMIT}/"


def is_ke_auto(printer: dict) -> bool:
    return printer.get("id") == KE_ID and printer.get("startup") == KE_AUTO_STARTUP


def _positive(printer: dict, name: str) -> float:
    value = float(printer[name])
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"KE başlangıç ayarı geçersiz: {name}")
    return value


def restore_limits_command(printer: dict) -> str:
    """Restore normal source-profile limits before homing and after setup/music."""
    velocity = _positive(printer, "max_velocity_mm_s")
    acceleration = _positive(printer, "max_accel_mm_s2")
    smoothing = _positive(printer, "max_accel_to_decel_mm_s2")
    scv = float(printer.get("square_corner_velocity_mm_s", 5))
    if not math.isfinite(scv) or scv < 0:
        raise ValueError("KE square_corner_velocity geçersiz.")
    return (f"SET_VELOCITY_LIMIT VELOCITY={velocity:g} ACCEL={acceleration:g} "
            f"ACCEL_TO_DECEL={smoothing:g} SQUARE_CORNER_VELOCITY={scv:g}")


def startup_commands(printer: dict) -> list[str]:
    """Commands after safe initial mode/mesh setup, before XY centering.

    No position is fabricated and no extra unhomed move is emitted.  Native
    G28 retains its actual endstop/probe sequence and normal motion limits.
    The optional wrapper slows only the stock direct Z-stepper hop.
    """
    if not is_ke_auto(printer):
        return []
    commands = [
        restore_limits_command(printer),
        "G28", "M400", "TURN_OFF_HEATERS", "G90",
    ]
    if printer.get("has_bed_mesh", True):
        commands.append("BED_MESH_CLEAR")
    commands += [
        "M204 S100", "G1 Z20.0000000 F180.000000", "M400", restore_limits_command(printer),
    ]
    return commands


def startup_report(printer: dict) -> dict:
    if not is_ke_auto(printer):
        return {"startup_mode": printer.get("startup", "prepared_only"), "automatic_homing": False}
    return {
        "startup_mode": KE_AUTO_STARTUP,
        "automatic_homing": True,
        "native_homing_command": "G28",
        "homing_axes": ["x", "y", "z"],
        "homing_uses_normal_profile_limits": True,
        "homing_toolhead_velocity_limit_mm_s": _positive(printer, "max_velocity_mm_s"),
        "homing_toolhead_acceleration_limit_mm_s2": _positive(printer, "max_accel_mm_s2"),
        "homing_toolhead_accel_to_decel_mm_s2": _positive(printer, "max_accel_to_decel_mm_s2"),
        "normal_profile_limits_restored_at_finish": True,
        "clearance_z_mm": CLEARANCE_Z_MM,
        "clearance_move_mm_s": CLEARANCE_Z_SPEED_MM_S,
        "clearance_move_acceleration_mm_s2": CLEARANCE_Z_ACCEL_MM_S2,
        "global_velocity_lowered_for_clearance": False,
        "explicit_clearance_move": "G1 Z20.0000000 F180.000000",
        "z_during_music": False,
        "stock_force_move_velocity_mm_s": 20.0,
        "stock_force_move_bypasses_toolhead_limits": True,
        "force_move_override_required_for_all_z_slow": True,
        "optional_wrapper": "reference/ke-startup/midi_ke_slow_z.cfg",
        "wrapper_installed_verified": False,
        "compiled_probe_speed_and_heating_verified": False,
        "homing_can_use_stock_heating_or_probe_routines": True,
        "heater_targets_cleared_after_homing": True,
        "native_homing_physical_tested": False,
        "no_fabricated_homing_position": True,
        "source_commit": SOURCE_COMMIT,
        "source_urls": {
            "toolhead": SOURCE_BASE + "klippy/toolhead.py",
            "force_move": SOURCE_BASE + "klippy/extras/force_move.py",
            "homing_override": SOURCE_BASE + "config/F005/sensorless.cfg",
            "probe_loader": SOURCE_BASE + "klippy/extras/prtouch_v2.py",
        },
    }
