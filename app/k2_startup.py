"""Native XY homing for K2 music without full Z/probe/nozzle-clean startup."""
from __future__ import annotations

from ke_startup import restore_limits_command

K2_IDS = frozenset(("creality_k2", "creality_k2_pro", "creality_k2_plus"))
K2_AUTO_STARTUP = "k2_xy_home"
SOURCE_COMMIT = "bc0a52078ace1e4d82995e396b38457b9f441024"
SOURCE_PATHS = {"creality_k2": "F021_CR0CN200400C10",
                "creality_k2_pro": "F012_CR0CN200400C10", "creality_k2_plus": "F008"}
STARTUP_NOTE = ("Dosya önce normal yazıcı limitlerini geri yükleyip G28 X Y ile otomatik home alır. "
                "Tabla boş olmalı; homing sırasında stok firmware'in Z güvenlik davranışı geçerlidir. "
                "Müzikte Z sabittir; bitişte normal limitler geri yüklenir.")


def is_k2_auto(printer: dict) -> bool:
    return printer.get("id") in K2_IDS and printer.get("startup") == K2_AUTO_STARTUP


def startup_commands(printer: dict) -> list[str]:
    if not is_k2_auto(printer):
        return []
    commands = [restore_limits_command(printer), "G28 X Y", "M400", "TURN_OFF_HEATERS", "G90"]
    # Native homing_override reloads its default mesh, so clear again after home.
    if printer.get("has_bed_mesh", True):
        commands.append("BED_MESH_CLEAR")
    return commands


def startup_report(printer: dict) -> dict:
    if not is_k2_auto(printer):
        return {"startup_mode": printer.get("startup", "prepared_only"), "automatic_homing": False}
    return {
        "startup_mode": K2_AUTO_STARTUP, "automatic_homing": True,
        "native_homing_command": "G28 X Y", "homing_axes": ["x", "y"],
        "homing_uses_normal_profile_limits": True,
        "homing_toolhead_velocity_limit_mm_s": printer["max_velocity_mm_s"],
        "homing_toolhead_acceleration_limit_mm_s2": printer["max_accel_mm_s2"],
        "homing_toolhead_accel_to_decel_mm_s2": printer["max_accel_to_decel_mm_s2"],
        "normal_profile_limits_restored_at_finish": True,
        "full_z_probe_or_nozzle_clean_requested": False,
        "explicit_z_moves": 0, "z_homed_by_file": False, "z_during_music": False,
        "clearance_managed_by_firmware": True, "clearance_z_mm": None,
        "native_homing_can_move_z": True,
        "native_homing_physical_tested": False, "no_fabricated_homing_position": True,
        "source_commit": SOURCE_COMMIT,
        "source_url": (f"https://github.com/CrealityOfficial/K2_Series_Klipper/blob/{SOURCE_COMMIT}/"
                       f"config/{SOURCE_PATHS[printer['id']]}/sensorless.cfg"),
    }
