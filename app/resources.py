"""Resource locations shared by source and frozen Windows builds."""
from pathlib import Path
import sys

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
APP = ROOT / "app"
ASSETS = APP / "assets"
