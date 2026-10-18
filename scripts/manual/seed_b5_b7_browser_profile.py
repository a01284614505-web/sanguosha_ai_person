"""旧文件名保留为转调：已改名为 seed_browser_profile.py。"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("seed_browser_profile.py")), run_name="__main__")
