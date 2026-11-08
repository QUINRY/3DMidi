"""Replay file startup through pinned U1 homing/kinematics code, without hardware.

Endstop triggers are emulated. This verifies the control path and Z displacement,
not the mechanical clearance or successful homing on the user's printer.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace


HASHES = {
    "corexy.py": "47a83a9e103b57ee0e5b673b7ec08b28352c24ddcee26503688749e4181b63ac",
    "homing_xyz_override.py": "65ccb29eb7ad6a88bb9cd276f74de2f1685c67f41b3bc71b75445a827f471aeb",
}


def load_classes(directory: Path):
    namespace = {"math": math}
    for filename, classname in [("corexy.py", "CoreXYKinematics"), ("homing_xyz_override.py", "HomingXYZOverride")]:
        data = (directory / filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != HASHES[filename]:
            raise ValueError("Unexpected U1 reference source")
        tree = ast.parse(data.decode("utf-8"))
        body = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname]
        exec(compile(ast.Module(body=body, type_ignores=[]), str(directory / filename), "exec"), namespace)
    return namespace


class Gcmd:
    def __init__(self, params):
        self.params = params

    def get(self, key, default=None):
        return self.params.get(key, default)

    def get_float(self, key, default=None, **_):
        value = self.get(key, default)
        return None if value is None else float(value)

    def get_int(self, key, default=0, **_):
        return int(self.get(key, default))

    def get_command_parameters(self):
        return dict(self.params)

    def get_raw_command_parameters(self):
        return " ".join(f"{key}={value}" if key not in "XYZ" else key for key, value in self.params.items())

    def error(self, message):
        return ValueError(message)


def replay(path: Path, directory: Path, *, z_homed=False, z_position=275.0) -> dict:
    if z_position < 20:
        raise ValueError("This startup requires an operator-prepared clearance of at least 20 mm")
    ns = load_classes(directory)
    kin = object.__new__(ns["CoreXYKinematics"])
    kin.limits = [(1.0, -1.0), (1.0, -1.0), (0.0, 275.0) if z_homed else (1.0, -1.0)]
    kin.ignore_check_move_limit = False
    kin.axes_min = (0, 0, 0)
    kin.axes_max = (271, 335, 275)
    kin.max_z_accel = 500.0
    position = [135.0, 135.0, z_position, 0.0]
    physical_z_moves = []
    endstop_axes = []
    rails = []
    for axis, maximum in enumerate((271.0, 335.0, 275.0)):
        rail = SimpleNamespace(
            axis=axis, get_range=lambda maximum=maximum: (0.0, maximum),
            get_homing_info=lambda axis=axis: SimpleNamespace(
                positive_dir=axis == 2, position_endstop=275.0 if axis == 2 else 0.0,
                speed=10.0 if axis == 2 else 40.0, homing_before_delay=0,
            ),
            set_position=lambda *_: None, get_endstops=lambda: [],
        )
        rails.append(rail)
    kin.rails = rails

    def set_position(pos, homing_axes=()):
        position[:] = pos
        kin.set_position(pos, homing_axes)

    def manual_move(pos, speed):
        end = [position[i] if value is None else value for i, value in enumerate(pos)]
        end += position[len(end):]
        if abs(end[2] - position[2]) > 1e-9:
            physical_z_moves.append({"distance": end[2] - position[2], "speed": speed})
        position[:] = end

    toolhead = SimpleNamespace(
        max_accel=300.0, kin=kin, get_kinematics=lambda: kin,
        get_position=lambda: list(position), set_position=set_position,
        manual_move=manual_move, wait_moves=lambda: None, flush_step_generation=lambda: None,
    )
    toolhead.set_accel = lambda value: setattr(toolhead, "max_accel", value)
    printer = SimpleNamespace(
        get_reactor=lambda: SimpleNamespace(monotonic=lambda: 0.0),
        command_error=ValueError,
        lookup_object=lambda name, default=None: toolhead if name == "toolhead" else default,
    )

    class ZHomingMove:
        def __init__(self, *_):
            pass

        def homing_move(self, target, speed, *_, **__):
            manual_move(target, speed)

    ns["homing"] = SimpleNamespace(HomingMove=ZHomingMove)
    override = object.__new__(ns["HomingXYZOverride"])
    override.printer = printer
    override.z_hop, override.z_hop_speed = 5.0, 5.0
    override.z_safe, override.z_safe_speed = 10.0, 30.0
    override.z_hop_homing_accel, override.z_probe_z_accel = 1000.0, 100.0
    override.z_raised, override.in_script, override.z_need_home = False, False, False
    empty_template = SimpleNamespace(run_gcode_from_command=lambda *a, **k: None)
    override.z_hop_homing_begin_gcode = override.z_hop_homing_end_gcode = empty_template

    def coarse_home(gcmd):
        axes = [i for i, axis in enumerate("XYZ") if gcmd.get(axis) is not None]
        if axes != [0, 1] and axes not in ([0], [1]):
            raise ValueError("Only real XY endstop homing is allowed")

        class HomingState:
            def get_axes(self):
                return axes

            def home_rails(self, selected_rails, forcepos, homepos):
                # Emulate the real endstop trigger, preserving Z and using
                # the actual CoreXY home()/set_position() implementations.
                end = [position[i] if value is None else value for i, value in enumerate(homepos)]
                end += position[len(end):]
                for rail in selected_rails:
                    endstop_axes.append(rail.axis)
                manual_move(end, 40.0)
                set_position(end, axes)

        kin.home(HomingState())

    override.prev_G28 = coarse_home

    def run_native_xy_template(_):
        # Stock _HOMING_PRECISE_COREXY_ADVANCED invokes SENSORLESS_HOME_Y
        # then SENSORLESS_HOME_X, each issuing nested G28 under in_script.
        override.cmd_G28_BASE(Gcmd({"Y": "0"}))
        override.cmd_G28_BASE(Gcmd({"X": "0"}))

    override.template = SimpleNamespace(create_template_context=lambda: {}, run_gcode_from_command=run_native_xy_template)

    for raw in path.read_text(encoding="ascii").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        command, *args = line.split()
        if command == "G28":
            params = {arg: "0" for arg in args if "=" not in arg}
            params.update(dict(arg.split("=", 1) for arg in args if "=" in arg))
            override.cmd_G28_BASE(Gcmd(params))
        elif command in {"G0", "G1"}:
            values = {arg[0]: float(arg[1:]) for arg in args}
            if "Z" in values:
                raise ValueError("Explicit Z motion in startup")
            target = [values.get("X", position[0]) + 0.115, values.get("Y", position[1]) - 0.008, position[2], 0.0]

            class Move:
                end_pos = target
                axes_d = [target[i] - position[i] for i in range(4)]

                def move_error(self, message):
                    return ValueError(message)

            kin.check_move(Move())
            if physical_z_moves:
                raise ValueError(f"Native startup would move Z: {physical_z_moves}")
            if set(endstop_axes) != {0, 1}:
                raise ValueError("Startup did not reference both real XY endstops")
            if ("z" in kin.get_status(0)["homed_axes"]) != z_homed:
                raise ValueError("Startup changed the Z homing flag")
            return {"file": path.name, "xy_endstops_referenced": True, "z_displacement_commands": 0,
                    "z_homed_before": z_homed, "z_homed_after": z_homed, "initial_z_reference": z_position,
                    "first_xy_move_accepted": True, "hardware_endstops": "emulated; physical printer test not performed"}
    raise ValueError("No XY motion to test")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("gcode", type=Path)
    p.add_argument("--reference-dir", type=Path, required=True)
    args = p.parse_args()
    print(replay(args.gcode, args.reference_dir))
