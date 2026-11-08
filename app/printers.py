"""Source-backed printer profiles and inert, local Klipper config imports.

Only numeric motion settings are read. Includes and macros are never resolved
or executed. Custom profiles live in memory for the current server process.
"""
from __future__ import annotations

import configparser
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import threading

from k2_startup import K2_AUTO_STARTUP, K2_IDS
from resources import APP


CATALOG = APP / "printer_catalog.json"
BAMBU_CATALOG = CATALOG.with_name("bambu_catalog.json")
DEFAULT_ID = "snapmaker_u1"
MAX_SUPPORTED_POSITION_MM = 10000.0
MAX_SUPPORTED_VELOCITY_MM_S = 10000.0
_lock = threading.RLock()
_factory_profiles: dict[str, dict] | None = None
_custom_profiles: dict[str, dict] = {}


def _finite(value, label: str, *, minimum: float | None = None,
            positive: bool = False, integer: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} için sayısal bir değer gerekli.") from exc
    if not math.isfinite(result) or (positive and result <= 0) or (
            minimum is not None and result < minimum):
        raise ValueError(f"{label} sonlu ve geçerli aralıkta olmalı.")
    if integer and result != int(result):
        raise ValueError(f"{label} pozitif tam sayı olmalı.")
    return result


def _gear_ratio(value, label: str = "gear_ratio") -> float:
    """Return motor rotations per driven rotation, including multiple gears."""
    if value is None or str(value).strip() == "":
        return 1.0
    if isinstance(value, (int, float)):
        return _finite(value, label, positive=True)
    product = 1.0
    for stage in str(value).split(","):
        parts = stage.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"{label}, 80:16 veya 80:16, 50:20 biçiminde olmalı.")
        numerator = _finite(parts[0], label, positive=True)
        denominator = _finite(parts[1], label, positive=True)
        product *= numerator / denominator
    return _finite(product, label, positive=True)


def cadence(axis: dict) -> float:
    """Full motor steps per mm; microsteps do not determine musical pitch."""
    full_steps = _finite(axis.get("full_steps_per_rotation", 200),
                         "full_steps_per_rotation", positive=True, integer=True)
    rotation = _finite(axis.get("rotation_distance"), "rotation_distance", positive=True)
    gearing = _gear_ratio(axis.get("gear_ratio"))
    return _finite(full_steps * gearing / rotation, "Motor adımı/mm", positive=True)


def _derive(profile: dict) -> dict:
    p = deepcopy(profile)
    p.pop("music_settings_lock", None)
    motor = p.get("motor_control", {})
    if (motor.get("type") == "foc_step_servo" and set(motor.get("axes", ())) & {"x", "y"}
            and p.get("music_settings_unlocked") is not True):
        p["music_settings_lock"] = {"speed": "slow", "tempo": "slow", "reason": "foc_step_servo"}
    if p.get("selectable") is not True:
        return p
    if p.get("firmware_family") == "bambu":
        if p.get("music_mode") != "bambu_native" or p.get("backend") != "bambu_m1006":
            raise ValueError("Bambu Lab için yalnızca doğrulanmış yerleşik müzik profili kullanılabilir.")
        # This backend addresses musical notes, not toolhead feedrates.
        # Never infer motor steps/mm from a Bambu Studio machine preset.
        p["startup"] = "native_sound"
        return p
    p.setdefault("firmware_family", "klipper")
    p.setdefault("music_mode", "xy_motion")
    if p.get("kinematics") not in {"corexy", "cartesian"}:
        raise ValueError("Bu kinematik desteklenmiyor. CoreXY veya Cartesian profil seç.")
    for name in ("x", "y"):
        axis = p[name]
        axis["min"] = _finite(axis.get("min", 0), f"{name.upper()} position_min")
        axis["max"] = _finite(axis.get("max"), f"{name.upper()} position_max")
        if max(abs(axis["min"]), abs(axis["max"])) > MAX_SUPPORTED_POSITION_MM:
            raise ValueError(f"{name.upper()} konumu uygulamanın desteklediği ±10000 mm aralığının dışında.")
        if axis["min"] >= axis["max"]:
            raise ValueError(f"{name.upper()} position_min, position_max değerinden küçük olmalı.")
        axis["fullsteps_per_mm"] = cadence(axis)
        axis["microsteps"] = int(_finite(axis.get("microsteps"),
                                        f"{name.upper()} microsteps", positive=True, integer=True))
    if p.get("axis_priority", "balanced") not in {"balanced", "y"}:
        raise ValueError("Geçersiz müzik ekseni önceliği.")
    if p.get("music_axes", "xy") not in {"x", "xy"}:
        raise ValueError("Geçersiz müzik ekseni.")
    if p.get("music_axes") == "x" and (p.get("axis_priority", "balanced") != "balanced" or (
            p["kinematics"] == "corexy" and not math.isclose(p["x"]["fullsteps_per_mm"], p["y"]["fullsteps_per_mm"]))):
        raise ValueError("Yalnızca X melodisi dengeli, eşit motor adımlı bir profil gerektirir.")
    if p.get("axis_priority") == "y" and (p["kinematics"] != "corexy" or not math.isclose(
            p["x"]["fullsteps_per_mm"], p["y"]["fullsteps_per_mm"])):
        raise ValueError("Y önceliği, eşit motor adımlı CoreXY profil gerektirir.")
    velocity = _finite(p.get("max_velocity_mm_s"), "max_velocity", positive=True)
    if velocity > MAX_SUPPORTED_VELOCITY_MM_S:
        raise ValueError("max_velocity uygulamanın desteklediği 10000 mm/sn sınırını aşıyor.")
    acceleration = _finite(p.get("max_accel_mm_s2"), "max_accel", positive=True)
    p["music_max_velocity_mm_s"] = min(360.0, velocity, _finite(
        p.get("music_max_velocity_mm_s", 360), "Müzik hız sınırı", positive=True))
    music_accel_ceiling = 20000.0 if p["id"] == DEFAULT_ID else 12000.0
    p["music_max_accel_mm_s2"] = min(music_accel_ceiling, acceleration, _finite(
        p.get("music_max_accel_mm_s2", 12000), "Müzik ivme sınırı", positive=True))
    p["square_corner_velocity_mm_s"] = _finite(
        p.get("square_corner_velocity_mm_s", 5), "square_corner_velocity", minimum=0)
    if "minimum_cruise_ratio" in p:
        ratio = _finite(p["minimum_cruise_ratio"], "minimum_cruise_ratio", minimum=0)
        if ratio >= 1:
            raise ValueError("minimum_cruise_ratio, 0 dahil ve 1 hariç aralığında olmalı.")
        p["minimum_cruise_ratio"] = ratio
    if p["id"] == DEFAULT_ID:
        p["music_bounds"] = {"x": [55.0, 215.0], "y": [55.0, 215.0]}
        p["route_bounds"] = {"x": [70.0, 200.0], "y": [70.0, 200.0]}
        p["start_xy"] = [135.0, 135.0]
    else:
        volume = p.get("build_volume_mm") or []
        music, route = {}, {}
        for index, name in enumerate(("x", "y")):
            axis = p[name]
            nominal = volume[index] if index < len(volume) and volume[index] is not None else axis["max"]
            nominal = _finite(nominal, f"{name.upper()} tabla boyutu", positive=True)
            lo, hi = max(0.0, axis["min"]), min(nominal, axis["max"])
            # Keep 20 mm from physical/nominal edges, then another 10 mm
            # for the planned musical path and its acceleration margins.
            music[name] = [lo + 20.0, hi - 20.0]
            route[name] = [lo + 30.0, hi - 30.0]
            if route[name][1] - route[name][0] <= 20.0:
                raise ValueError(f"{name.upper()} hareket alanı güvenli müzik yolu için çok dar (80 mm'den geniş olmalı).")
        p["music_bounds"], p["route_bounds"] = music, route
        p["start_xy"] = [sum(music[name]) / 2 for name in ("x", "y")]
        p["startup"] = ("ke_auto_home_slow_z" if p["id"] == "creality_ender3_v3_ke"
                        else K2_AUTO_STARTUP if p["id"] in K2_IDS else "prepared_only")
    return p


def _catalog_profiles() -> dict[str, dict]:
    global _factory_profiles
    if _factory_profiles is None:
        try:
            data = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
            profiles = data["profiles"]
            profiles += json.loads(BAMBU_CATALOG.read_text(encoding="utf-8-sig"))["profiles"]
            if len({p["id"] for p in profiles}) != len(profiles):
                raise ValueError("Yazıcı kataloğunda yinelenen profil var.")
            _factory_profiles = {p["id"]: _derive(p) for p in profiles}
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Yazıcı profil kataloğu okunamadı.") from exc
    return _factory_profiles


def public_profiles() -> list[dict]:
    """Return detached public profiles, including unavailable catalog entries."""
    with _lock:
        return deepcopy([*_catalog_profiles().values(), *_custom_profiles.values()])


def get_profile(profile_id: str = DEFAULT_ID) -> dict:
    """Get a selectable profile; unavailable/unknown models never fall back."""
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("Geçersiz yazıcı profili. Listeden bir yazıcı seç.")
    with _lock:
        profile = _custom_profiles.get(profile_id) or _catalog_profiles().get(profile_id)
        if profile is None:
            raise ValueError("Yazıcı profili bulunamadı. Listeden bir yazıcı seç.")
        if profile.get("selectable") is not True:
            if profile.get("firmware_family") == "bambu":
                raise ValueError("Bu Bambu Lab modelinde yerleşik müzik desteği doğrulanmadı; Klipper komutları veya printer.cfg ile çıktı oluşturulamaz.")
            if profile.get("status") == "unsupported_kinematics":
                raise ValueError("Bu yazıcının kinematiği desteklenmiyor. CoreXY veya Cartesian profil seç.")
            raise ValueError("Bu model için eksiksiz printer.cfg gerekli. Yazıcı seçiminden konfigürasyonunu içe aktar.")
        return deepcopy(profile)


def import_profile(filename: str, text: str, *, register: bool = True) -> dict:
    """Parse complete numeric Klipper sections without resolving any include."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("printer.cfg dosyası boş veya okunamıyor.")
    if len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("printer.cfg en fazla 1 MB olabilir.")
    if not isinstance(filename, str) or not filename.lower().endswith(".cfg"):
        raise ValueError("Lütfen .cfg uzantılı bir yazıcı konfigürasyonu seç.")
    # Names are display metadata only: remove directories and control bytes.
    safe_name = re.sub(r"[\x00-\x1f\x7f]", "", filename.replace("\\", "/").rsplit("/", 1)[-1])[:160] or "printer.cfg"
    parser = configparser.ConfigParser(
        interpolation=None, strict=False, allow_no_value=True,
        inline_comment_prefixes=("#", ";"), default_section="__no_inherited_defaults__")
    try:
        parser.read_string(text.lstrip("\ufeff"))
    except configparser.Error as exc:
        raise ValueError("printer.cfg okunamadı. Bölüm ve anahtar biçimlerini kontrol et; eksiksiz konfigürasyonu yükle.") from exc
    # Klipper does not inherit ConfigParser DEFAULT options. Require the
    # actual numeric options inside each named motion section.
    parser.defaults().clear()
    sections = {name.lower(): name for name in parser.sections()}
    missing = [name for name in ("printer", "stepper_x", "stepper_y") if name not in sections]
    if missing:
        raise ValueError("Eksik bölüm: " + ", ".join(f"[{name}]" for name in missing)
                         + ". Include dosyaları otomatik açılmaz; bu bölümlerin tüm değerlerini içeren printer.cfg yükle.")

    def value(section: str, key: str, default=None):
        return parser.get(sections[section], key, fallback=default)

    def numeric(section: str, key: str, default=None, *, positive=True, integer=False, minimum=None):
        raw = value(section, key, default)
        if raw is None:
            raise ValueError(f"[{section}] {key} eksik. Include içindeki değerleri de içeren eksiksiz konfigürasyonu yükle.")
        return _finite(raw, f"[{section}] {key}", positive=positive, integer=integer, minimum=minimum)

    kinematics = (value("printer", "kinematics") or "").strip().lower()
    if kinematics not in {"corexy", "cartesian"}:
        raise ValueError("Yalnızca CoreXY ve Cartesian kinematik desteklenir; [printer] kinematics değerini kontrol et.")
    velocity = numeric("printer", "max_velocity")
    acceleration = numeric("printer", "max_accel")
    axes = {}
    defaults_used = []
    for name in ("x", "y"):
        section = "stepper_" + name
        axis = {
            "min": numeric(section, "position_min", 0, positive=False),
            "max": numeric(section, "position_max", positive=False),
            "rotation_distance": numeric(section, "rotation_distance"),
            "microsteps": int(numeric(section, "microsteps", integer=True)),
            "full_steps_per_rotation": int(numeric(section, "full_steps_per_rotation", 200, integer=True)),
        }
        if value(section, "gear_ratio") is not None:
            axis["gear_ratio"] = value(section, "gear_ratio")
            _gear_ratio(axis["gear_ratio"], f"[{section}] gear_ratio")
        for key, fallback in (("position_min", 0), ("full_steps_per_rotation", 200)):
            if not parser.has_option(sections[section], key):
                defaults_used.append(f"[{section}] {key}={fallback}")
        axes[name] = axis
    scv = numeric("printer", "square_corner_velocity", 5, positive=False, minimum=0)
    if not parser.has_option(sections["printer"], "square_corner_velocity"):
        defaults_used.append("[printer] square_corner_velocity=5")
    dimensions = [axes["x"]["max"], axes["y"]["max"]]
    if "stepper_z" in sections and value("stepper_z", "position_max") is not None:
        dimensions.append(numeric("stepper_z", "position_max"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    profile = {
        "id": "custom_" + digest[:20], "name": "Özel yazıcı · " + safe_name,
        "manufacturer": "Özel konfigürasyon", "selectable": True,
        "status": "imported_config", "kinematics": kinematics,
        "build_volume_mm": dimensions, **axes,
        "max_velocity_mm_s": velocity, "max_accel_mm_s2": acceleration,
        "music_max_velocity_mm_s": min(360.0, velocity),
        "music_max_accel_mm_s2": min(12000.0, acceleration),
        "square_corner_velocity_mm_s": scv,
        "startup": "prepared_only", "has_bed_mesh": "bed_mesh" in sections,
        "source": {"kind": "imported_config", "filename": safe_name, "sha256": digest},
        "notes": ["Yerel printer.cfg değerlerinden oluşturuldu; fiziksel test yapılmadı.",
                  "Tüm eksenleri önceden home al, motorları etkin tut ve en az 20 mm nozul–tabla boşluğu bırak. Otomatik home ve Z hareketi üretilmez.",
                  "Include dosyaları ve makrolar çalıştırılmaz; gereken sayısal değerler bu dosyada bulunmalıdır."],
        "assumptions": defaults_used,
    }
    if defaults_used:
        profile["notes"].append("Klipper varsayılanları kullanıldı: " + "; ".join(defaults_used) + ".")
    if value("printer", "max_accel_to_decel") is not None:
        profile["max_accel_to_decel_mm_s2"] = numeric("printer", "max_accel_to_decel", positive=False, minimum=0)
    if value("printer", "minimum_cruise_ratio") is not None:
        profile["minimum_cruise_ratio"] = numeric("printer", "minimum_cruise_ratio", positive=False, minimum=0)
    derived = _derive(profile)
    if register:
        with _lock:
            _custom_profiles[derived["id"]] = derived
    return deepcopy(derived)
