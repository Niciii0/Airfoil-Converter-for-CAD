import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
import numpy as np
import subprocess
import tempfile
import urllib.request
import zipfile
import shutil
import csv
import re
import json
import math
import sys

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ---------------------- Core math ----------------------

UIUC_ZIP_URL = "https://m-selig.ae.illinois.edu/ads/coord_seligFmt.zip"


def app_base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def app_user_dir():
    root = Path.home() / "AppData" / "Roaming" / "Airfoil Converter"
    root.mkdir(parents=True, exist_ok=True)
    return root


def bundled_path(*parts):
    return app_base_dir().joinpath(*parts)


def load_airfoil_xz(file_path: Path):
    try:
        data = np.loadtxt(file_path, skiprows=1)
        if data.ndim != 2 or data.shape[1] < 2:
            raise ValueError("Invalid data shape after skiprows=1")
    except Exception:
        data = np.loadtxt(file_path, skiprows=0)

    x = data[:, 0].astype(float).copy()
    z = data[:, 1].astype(float).copy()

    # TE fix
    x[0], z[0] = 1.0, 0.0
    x[-1], z[-1] = 1.0, 0.0

    # Remove consecutive duplicates
    pts = np.column_stack((x, z))
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.any(np.abs(pts[1:] - pts[:-1]) > 1e-12, axis=1)

    x = x[keep]
    z = z[keep]
    y = np.zeros_like(x)
    return x, y, z


def transform_points(x, y, z, size, rx_deg, ry_deg, rz_deg, ox, oy, oz):
    size = float(size)
    rx = np.deg2rad(float(rx_deg))
    ry = np.deg2rad(float(ry_deg))
    rz = np.deg2rad(float(rz_deg))

    x = x * size
    y = y * size
    z = z * size

    Rx = np.array([
        [1, 0, 0],
        [0, np.cos(rx), -np.sin(rx)],
        [0, np.sin(rx),  np.cos(rx)]
    ], dtype=float)

    Ry = np.array([
        [np.cos(ry), 0, np.sin(ry)],
        [0,          1, 0],
        [-np.sin(ry), 0, np.cos(ry)]
    ], dtype=float)

    Rz = np.array([
        [np.cos(rz), -np.sin(rz), 0],
        [np.sin(rz),  np.cos(rz), 0],
        [0,           0,          1]
    ], dtype=float)

    R = Rz @ Ry @ Rx
 
    pts = np.column_stack((x, y, z))
    pts = (R @ pts.T).T
    pts += np.array([float(ox), float(oy), float(oz)], dtype=float)

    return pts[:, 0], pts[:, 1], pts[:, 2]


def export_xyz(out_path: Path, x, y, z):
    table = np.column_stack((x, y, z))
    np.savetxt(out_path, table, fmt="%.6f", comments="")


def safe_float(s, default=0.0):
    try:
        return float(s)
    except Exception:
        return float(default)


def safe_int(s, default=9):
    try:
        return int(float(s))
    except Exception:
        return int(default)


def sanitize_name(name: str):
    return re.sub(r"[^A-Za-z0-9_\-\.]+", "_", name)


def export_airfoil_for_xfoil(src_path: Path, dst_path: Path):
    x, _, z = load_airfoil_xz(src_path)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(dst_path.stem + "\n")
        for xi, zi in zip(x, z):
            f.write(f"{xi:.6f} {zi:.6f}\n")


def parse_xfoil_polar_file(polar_path: Path):
    alpha, cl, cd, cdp, cm, xtr_top, xtr_bot = [], [], [], [], [], [], []

    with open(polar_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    data_started = False
    for line in lines:
        if "----" in line:
            data_started = True
            continue
        if not data_started:
            continue

        parts = line.strip().split()
        if len(parts) < 7:
            continue

        try:
            alpha.append(float(parts[0]))
            cl.append(float(parts[1]))
            cd.append(float(parts[2]))
            cdp.append(float(parts[3]))
            cm.append(float(parts[4]))
            xtr_top.append(float(parts[5]))
            xtr_bot.append(float(parts[6]))
        except Exception:
            pass

    if not alpha:
        raise ValueError("No valid polar data found in XFOIL output.")

    return {
        "alpha": np.array(alpha),
        "cl": np.array(cl),
        "cd": np.array(cd),
        "cdp": np.array(cdp),
        "cm": np.array(cm),
        "xtr_top": np.array(xtr_top),
        "xtr_bot": np.array(xtr_bot),
    }


def run_xfoil_polar(xfoil_exe: Path, airfoil_path: Path, reynolds, mach, ncrit,
                    alpha_start, alpha_end, alpha_step):
    if not xfoil_exe.exists():
        raise FileNotFoundError(f"XFOIL executable not found: {xfoil_exe}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        foil_dat = td / f"{sanitize_name(airfoil_path.stem)}.dat"
        polar_out = td / "polar.txt"

        export_airfoil_for_xfoil(airfoil_path, foil_dat)

        cmd_lines = [
            f"LOAD {foil_dat.name}",
            "",
            "PANE",
            "OPER",
            f"VISC {float(reynolds)}",
            f"MACH {float(mach)}",
            "VPAR",
            f"N {int(ncrit)}",
            "",
            "ITER 200",
            "PACC",
            f"{polar_out.name}",
            "",
            f"ASEQ {float(alpha_start)} {float(alpha_end)} {float(alpha_step)}",
            "",
            "QUIT"
        ]

        result = subprocess.run(
            [str(xfoil_exe)],
            cwd=td,
            input="\n".join(cmd_lines),
            text=True,
            capture_output=True,
            timeout=120
        )

        if result.returncode != 0 and not polar_out.exists():
            raise RuntimeError(
                "XFOIL failed.\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}"
            )

        if not polar_out.exists():
            raise RuntimeError(
                "XFOIL did not generate a polar file.\n"
                "Try a smaller alpha range or different Reynolds number."
            )

        return parse_xfoil_polar_file(polar_out)


def run_xfoil_polar_retry(xfoil_exe: Path, airfoil_path: Path, reynolds, mach, ncrit,
                          alpha_start, alpha_end, alpha_step):
    attempts = [
        (alpha_start, alpha_end, alpha_step),
        (alpha_start, alpha_end, max(alpha_step / 2.0, 0.1)),
        (max(alpha_start, -2.0), min(alpha_end, 10.0), max(alpha_step / 2.0, 0.1)),
    ]
    last_error = None
    for a0, a1, astep in attempts:
        try:
            return run_xfoil_polar(xfoil_exe, airfoil_path, reynolds, mach, ncrit, a0, a1, astep)
        except Exception as e:
            last_error = e
    raise last_error


def save_polar_csv(csv_path: Path, polar_dict):
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["alpha_deg", "CL", "CD", "CDp", "CM", "Top_Xtr", "Bot_Xtr"])
        for row in zip(
            polar_dict["alpha"],
            polar_dict["cl"],
            polar_dict["cd"],
            polar_dict["cdp"],
            polar_dict["cm"],
            polar_dict["xtr_top"],
            polar_dict["xtr_bot"]
        ):
            writer.writerow(row)


def get_airfoil_files(folder: Path):
    return sorted(list(folder.glob("*.txt")) + list(folder.glob("*.dat")))


def load_airfoil_named(path: Path):
    x, y, z = load_airfoil_xz(path)
    return x, z


def split_upper_lower(x, z):
    if len(x) < 4:
        raise ValueError("Need at least 4 coordinate points.")
    le_idx = int(np.argmin(x))
    upper_x = np.asarray(x[:le_idx + 1], dtype=float)
    upper_z = np.asarray(z[:le_idx + 1], dtype=float)
    lower_x = np.asarray(x[le_idx:], dtype=float)
    lower_z = np.asarray(z[le_idx:], dtype=float)

    upper_order = np.argsort(upper_x)
    lower_order = np.argsort(lower_x)
    return (
        upper_x[upper_order], upper_z[upper_order],
        lower_x[lower_order], lower_z[lower_order]
    )


def unique_xy_for_interp(x, z):
    x = np.asarray(x, dtype=float)
    z = np.asarray(z, dtype=float)
    order = np.argsort(x)
    x = x[order]
    z = z[order]
    ux, inv = np.unique(np.round(x, 12), return_inverse=True)
    uz = np.zeros_like(ux, dtype=float)
    counts = np.zeros_like(ux, dtype=float)
    for idx, group in enumerate(inv):
        uz[group] += z[idx]
        counts[group] += 1
    uz /= np.maximum(counts, 1)
    return ux, uz


def analyze_airfoil_geometry(path: Path):
    x, z = load_airfoil_named(path)
    ux, uz, lx, lz = split_upper_lower(x, z)
    ux, uz = unique_xy_for_interp(ux, uz)
    lx, lz = unique_xy_for_interp(lx, lz)

    xmin = max(float(np.min(ux)), float(np.min(lx)))
    xmax = min(float(np.max(ux)), float(np.max(lx)))
    grid = np.linspace(xmin, xmax, 400)
    zu = np.interp(grid, ux, uz)
    zl = np.interp(grid, lx, lz)
    thickness = zu - zl
    camber = (zu + zl) / 2.0

    t_idx = int(np.argmax(thickness))
    c_idx = int(np.argmax(np.abs(camber)))
    chord = float(np.max(x) - np.min(x))
    te_gap = float(abs(z[0] - z[-1]))
    duplicate_steps = int(np.sum(np.hypot(np.diff(x), np.diff(z)) < 1e-10))
    normalized = abs(float(np.min(x))) < 1e-3 and abs(float(np.max(x)) - 1.0) < 1e-3
    malformed = bool(chord <= 0 or len(x) < 6 or np.any(~np.isfinite(x)) or np.any(~np.isfinite(z)))

    le_radius = 0.0
    try:
        le_idx = int(np.argmin(x))
        sample = slice(max(0, le_idx - 3), min(len(x), le_idx + 4))
        xs = x[sample]
        zs = z[sample]
        if len(xs) >= 3:
            a = np.column_stack((2 * xs, 2 * zs, np.ones_like(xs)))
            b = xs ** 2 + zs ** 2
            cx, cz, c = np.linalg.lstsq(a, b, rcond=None)[0]
            le_radius = float(math.sqrt(max(c + cx ** 2 + cz ** 2, 0.0)))
    except Exception:
        le_radius = 0.0

    return {
        "point_count": int(len(x)),
        "chord": chord,
        "max_thickness": float(thickness[t_idx]),
        "max_thickness_pct": float(thickness[t_idx] / chord * 100.0) if chord else 0.0,
        "max_thickness_x": float(grid[t_idx]),
        "max_camber": float(camber[c_idx]),
        "max_camber_pct": float(abs(camber[c_idx]) / chord * 100.0) if chord else 0.0,
        "max_camber_x": float(grid[c_idx]),
        "leading_edge_radius": le_radius,
        "te_gap": te_gap,
        "duplicate_steps": duplicate_steps,
        "normalized": normalized,
        "malformed": malformed,
    }


def repanel_airfoil(x, z, n_points):
    n_points = max(int(n_points), 10)
    d = np.hypot(np.diff(x), np.diff(z))
    s = np.insert(np.cumsum(d), 0, 0.0)
    if s[-1] <= 0:
        raise ValueError("Cannot repanel a zero-length airfoil.")
    target = np.linspace(0.0, s[-1], n_points)
    return np.interp(target, s, x), np.interp(target, s, z)


def smooth_airfoil(x, z, passes=1):
    x2 = np.asarray(x, dtype=float).copy()
    z2 = np.asarray(z, dtype=float).copy()
    for _ in range(max(int(passes), 1)):
        if len(x2) > 4:
            x2[1:-1] = (x2[:-2] + 2 * x2[1:-1] + x2[2:]) / 4.0
            z2[1:-1] = (z2[:-2] + 2 * z2[1:-1] + z2[2:]) / 4.0
    return x2, z2


def write_airfoil_dat(path: Path, name, x, z):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{name}\n")
        for xi, zi in zip(x, z):
            f.write(f"{xi:.8f} {zi:.8f}\n")


def cleanup_airfoil_file(src_path: Path, out_path: Path, mode, n_points=160):
    x, z = load_airfoil_named(src_path)
    mode = mode.lower()

    if mode == "normalize chord":
        xmin = float(np.min(x))
        chord = float(np.max(x) - xmin)
        if chord <= 0:
            raise ValueError("Cannot normalize an airfoil with zero chord.")
        x = (x - xmin) / chord
        z = z / chord
    elif mode == "repanel":
        x, z = repanel_airfoil(x, z, n_points)
    elif mode == "close trailing edge":
        x[0], z[0] = 1.0, 0.0
        x[-1], z[-1] = 1.0, 0.0
    elif mode == "flip order":
        x = x[::-1]
        z = z[::-1]
    elif mode == "smooth":
        x, z = smooth_airfoil(x, z, passes=2)
    elif mode == "remove duplicates":
        pts = np.column_stack((x, z))
        keep = np.ones(len(pts), dtype=bool)
        keep[1:] = np.hypot(np.diff(x), np.diff(z)) > 1e-10
        x = x[keep]
        z = z[keep]
    else:
        raise ValueError(f"Unknown cleanup mode: {mode}")

    write_airfoil_dat(out_path, out_path.stem, x, z)
    return out_path


def polar_summary(polar):
    cl = polar["cl"]
    cd = polar["cd"]
    alpha = polar["alpha"]
    valid = cd > 0
    if not np.any(valid):
        return "No positive CD values."
    ld = np.where(valid, cl / cd, np.nan)
    best_idx = int(np.nanargmax(ld))
    cl_idx = int(np.argmax(cl))
    return (
        f"max CL={cl[cl_idx]:.3f} at alpha={alpha[cl_idx]:.2f} deg | "
        f"best CL/CD={ld[best_idx]:.1f} at alpha={alpha[best_idx]:.2f} deg"
    )


UNIT_FACTORS = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "inch": 25.4,
}


def unit_factor(unit_name):
    return UNIT_FACTORS.get(unit_name, 1.0)


def sample_airfoil_points(path: Path, n_points=180):
    x, _, z = load_airfoil_xz(path)
    return repanel_airfoil(x, z, n_points)


def blend_airfoil_files(path_a: Path, path_b: Path, out_path: Path, blend_t, n_points=180):
    xa, za = sample_airfoil_points(path_a, n_points)
    xb, zb = sample_airfoil_points(path_b, n_points)
    t = float(np.clip(blend_t, 0.0, 1.0))
    x = xa * (1.0 - t) + xb * t
    z = za * (1.0 - t) + zb * t
    write_airfoil_dat(out_path, out_path.stem, x, z)
    return out_path


def triangulated_wing_mesh(items, unit_scale=1.0):
    stations = sorted(items, key=lambda it: it["oy"])
    vertices = []
    section_count = 0
    points_per_section = None

    for it in stations:
        x, y, z = load_airfoil_xz(it["path"])
        if points_per_section is None:
            points_per_section = len(x)
        elif len(x) != points_per_section:
            x, z = repanel_airfoil(x, z, points_per_section)
            y = np.zeros_like(x)

        x2, y2, z2 = transform_points(
            x, y, z,
            it["size"], it["rx"], it["ry"], it["rz"],
            it["ox"], it["oy"], it["oz"]
        )
        for row in zip(x2 * unit_scale, y2 * unit_scale, z2 * unit_scale):
            vertices.append(tuple(float(v) for v in row))
        section_count += 1

    faces = []
    if section_count >= 2 and points_per_section:
        for s in range(section_count - 1):
            a0 = s * points_per_section
            b0 = (s + 1) * points_per_section
            for i in range(points_per_section - 1):
                faces.append((a0 + i, a0 + i + 1, b0 + i + 1))
                faces.append((a0 + i, b0 + i + 1, b0 + i))

    return vertices, faces


def write_obj(path: Path, vertices, faces):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Airfoil Converter V6 wing mesh\n")
        for v in vertices:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for a, b, c in faces:
            f.write(f"f {a + 1} {b + 1} {c + 1}\n")


def face_normal(a, b, c):
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    vc = np.asarray(c, dtype=float)
    n = np.cross(vb - va, vc - va)
    length = np.linalg.norm(n)
    if length <= 0:
        return (0.0, 0.0, 0.0)
    return tuple((n / length).tolist())


def write_ascii_stl(path: Path, vertices, faces, name="airfoil_converter_wing"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"solid {sanitize_name(name)}\n")
        for a, b, c in faces:
            n = face_normal(vertices[a], vertices[b], vertices[c])
            f.write(f"  facet normal {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
            f.write("    outer loop\n")
            for idx in (a, b, c):
                v = vertices[idx]
                f.write(f"      vertex {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write(f"endsolid {sanitize_name(name)}\n")


def polar_score(polar):
    alpha = polar["alpha"]
    cl = polar["cl"]
    cd = polar["cd"]
    cm = polar["cm"]
    valid_cd = cd > 0
    ld = np.where(valid_cd, cl / cd, np.nan)
    max_cl_i = int(np.argmax(cl))
    min_cd_i = int(np.argmin(cd))
    best_ld_i = int(np.nanargmax(ld)) if np.any(np.isfinite(ld)) else 0
    zero_lift_alpha = float("nan")
    try:
        sign_changes = np.where(np.signbit(cl[:-1]) != np.signbit(cl[1:]))[0]
        if len(sign_changes):
            i = int(sign_changes[0])
            zero_lift_alpha = float(np.interp(0.0, [cl[i], cl[i + 1]], [alpha[i], alpha[i + 1]]))
    except Exception:
        pass
    return {
        "max_cl": float(cl[max_cl_i]),
        "stall_alpha": float(alpha[max_cl_i]),
        "min_cd": float(cd[min_cd_i]),
        "min_cd_alpha": float(alpha[min_cd_i]),
        "best_ld": float(ld[best_ld_i]) if np.isfinite(ld[best_ld_i]) else float("nan"),
        "best_ld_alpha": float(alpha[best_ld_i]),
        "zero_lift_alpha": zero_lift_alpha,
        "cm_at_best_ld": float(cm[best_ld_i]),
    }


# ---------------------- GUI app ----------------------

class AirfoilApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Airfoil Converter V6.2 - Wing Design Tool")
        self.geometry("1400x850")

        self.settings_file = app_user_dir() / "gui_settings.json"
        self.all_airfoils = []

        default_airfoil_dir = bundled_path("Airfoil_DATA")
        self.airfoil_dir = default_airfoil_dir if default_airfoil_dir.exists() else Path.cwd()
        self.export_dir = Path.home() / "Documents" / "Airfoil Converter Exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

        default_xfoil = bundled_path("xfoil.exe")
        self.xfoil_path = default_xfoil if default_xfoil.exists() else Path("")
        self.items = []
        self.current_polar = None
        self.current_polar_name = None
        self.polar_results = {}
        self.live_preview_after_id = None
        self.loading_selection = False
        self.item_counter = 0
        self.undo_stack = []
        self.redo_stack = []
        self.favorites = set()
        self.favorites_file = app_user_dir() / "favorites.json"
        self.project_folder = self.export_dir
        self.show_3d_grid = tk.BooleanVar(value=True)
        self.show_3d_axes = tk.BooleanVar(value=True)
        self.checked_items = set()

        self._build_ui()
        self.load_settings()
        self.load_favorites()
        self._refresh_airfoil_dropdown()
        self._refresh_plot()

        self.state("zoomed")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- settings ----------

    def save_settings(self, show_message=True):
        settings = {
            "airfoil_dir": str(self.airfoil_dir),
            "export_dir": str(self.export_dir),
            "xfoil_path": str(self.xfoil_path),

            "size": self.size_var.get(),
            "rx": self.rx_var.get(),
            "ry": self.ry_var.get(),
            "rz": self.rz_var.get(),
            "ox": self.ox_var.get(),
            "oy": self.oy_var.get(),
            "oz": self.oz_var.get(),

            "re": self.re_var.get(),
            "mach": self.mach_var.get(),
            "ncrit": self.ncrit_var.get(),
            "alpha_start": self.alpha_start_var.get(),
            "alpha_end": self.alpha_end_var.get(),
            "alpha_step": self.alpha_step_var.get(),

            "search": self.search_var.get(),
            "search_filter": self.search_filter_var.get(),
            "export_profile": self.export_profile_var.get(),
            "unit": self.unit_var.get(),
            "selected_airfoil": self.airfoil_var.get()
        }

        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)

        if show_message:
            messagebox.showinfo("Settings saved", "GUI settings saved successfully.")

    def load_settings(self):
        if not self.settings_file.exists():
            return

        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)

            self.airfoil_dir = Path(settings.get("airfoil_dir", str(self.airfoil_dir)))
            if not self.airfoil_dir.exists() and bundled_path("Airfoil_DATA").exists():
                self.airfoil_dir = bundled_path("Airfoil_DATA")
            self.export_dir = Path(settings.get("export_dir", str(self.export_dir)))
            self.export_dir.mkdir(parents=True, exist_ok=True)

            xfoil = settings.get("xfoil_path", "")
            if xfoil:
                self.xfoil_path = Path(xfoil)
            if (not self.xfoil_path or not self.xfoil_path.exists()) and bundled_path("xfoil.exe").exists():
                self.xfoil_path = bundled_path("xfoil.exe")

            self.size_var.set(settings.get("size", "1.0"))
            self.rx_var.set(settings.get("rx", "0"))
            self.ry_var.set(settings.get("ry", "0"))
            self.rz_var.set(settings.get("rz", "0"))
            self.ox_var.set(settings.get("ox", "0"))
            self.oy_var.set(settings.get("oy", "0"))
            self.oz_var.set(settings.get("oz", "0"))

            self.re_var.set(settings.get("re", "500000"))
            self.mach_var.set(settings.get("mach", "0.0"))
            self.ncrit_var.set(settings.get("ncrit", "9"))
            self.alpha_start_var.set(settings.get("alpha_start", "-5"))
            self.alpha_end_var.set(settings.get("alpha_end", "15"))
            self.alpha_step_var.set(settings.get("alpha_step", "0.5"))

            self.search_var.set(settings.get("search", ""))
            self.search_filter_var.set(settings.get("search_filter", "All"))
            self.export_profile_var.set(settings.get("export_profile", "Plain XYZ"))
            self.unit_var.set(settings.get("unit", "mm"))

            self.airfoil_dir_lbl.config(text=f"Airfoil folder: {self.airfoil_dir}")
            self.export_dir_lbl.config(text=f"Export folder: {self.export_dir}")

            if str(self.xfoil_path):
                self.xfoil_lbl.config(text=f"XFOIL: {self.xfoil_path}")

            self._refresh_airfoil_dropdown()

            saved_selected = settings.get("selected_airfoil", "")
            if saved_selected and saved_selected in self.all_airfoils:
                self.airfoil_var.set(saved_selected)

        except Exception as e:
            print("Settings load failed:", e)

    def on_close(self):
        try:
            self.save_settings(show_message=False)
        except Exception:
            pass
        self.destroy()

    # ---------- search ----------

    def filter_airfoils(self, event=None):
        search = self.search_var.get().lower().strip()
        active_filter = self.search_filter_var.get() if hasattr(self, "search_filter_var") else "All"

        if search == "":
            filtered = self.all_airfoils
        else:
            filtered = [a for a in self.all_airfoils if search in a.lower()]

        filtered = [a for a in filtered if self.matches_airfoil_filter(a, active_filter)]

        self.airfoil_combo["values"] = filtered

        if filtered:
            current = self.airfoil_var.get()
            if current not in filtered:
                self.airfoil_var.set(filtered[0])
        else:
            self.airfoil_var.set("")

    def matches_airfoil_filter(self, name, active_filter):
        if active_filter == "Favorites":
            return name in self.favorites
        low = name.lower()
        digits = "".join(ch for ch in low.replace("naca", "") if ch.isdigit())
        is_naca4 = ("naca" in low or low.startswith("n")) and len(digits) >= 4
        camber_digit = int(digits[0]) if is_naca4 else None
        thickness = int(digits[-2:]) if is_naca4 else None

        if active_filter == "All":
            return True
        if active_filter == "NACA":
            return is_naca4
        if active_filter == "Symmetric NACA":
            return is_naca4 and camber_digit == 0
        if active_filter == "Cambered NACA":
            return is_naca4 and camber_digit and camber_digit > 0
        if active_filter == "Thin <=10%":
            return is_naca4 and thickness is not None and thickness <= 10
        if active_filter == "Medium 10-15%":
            return is_naca4 and thickness is not None and 10 < thickness < 15
        if active_filter == "Thick >=15%":
            return is_naca4 and thickness is not None and thickness >= 15
        return True

    def load_favorites(self):
        try:
            if self.favorites_file.exists():
                with open(self.favorites_file, "r", encoding="utf-8") as f:
                    self.favorites = set(json.load(f))
        except Exception:
            self.favorites = set()

    def save_favorites(self):
        try:
            with open(self.favorites_file, "w", encoding="utf-8") as f:
                json.dump(sorted(self.favorites), f, indent=4)
        except Exception:
            pass

    def toggle_favorite(self):
        name = self.airfoil_var.get().strip()
        if not name:
            return
        if name in self.favorites:
            self.favorites.remove(name)
        else:
            self.favorites.add(name)
        self.save_favorites()
        self.filter_airfoils()

    # ---------- UI layout ----------

    def _setup_style(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure("Primary.TButton", padding=(10, 5))
        self.style.configure("Secondary.TButton", padding=(8, 4))
        self.style.configure("Tool.TButton", padding=(8, 3))
        self.style.configure("Invalid.TEntry", fieldbackground="#ffe8e8")
        self.style.configure("Status.TLabel", padding=(8, 4))

    def make_collapsible(self, parent, title, open_by_default=True):
        outer = ttk.Frame(parent)
        outer.pack(fill="x", pady=(0, 8))
        expanded = tk.BooleanVar(value=open_by_default)
        body = ttk.Frame(outer, padding=(8, 6))

        def toggle():
            if expanded.get():
                body.pack_forget()
                expanded.set(False)
                button.config(text=f"+ {title}")
            else:
                body.pack(fill="x")
                expanded.set(True)
                button.config(text=f"- {title}")
                self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

        button = ttk.Button(outer, text=f"- {title}" if open_by_default else f"+ {title}", command=toggle, style="Tool.TButton")
        button.pack(fill="x")
        if open_by_default:
            body.pack(fill="x")
        return body

    def _build_ui(self):
        self._setup_style()
        main = ttk.Frame(self, padding=10)
        main.pack(fill="both", expand=True)

        main_pane = ttk.PanedWindow(main, orient="horizontal")
        main_pane.pack(fill="both", expand=True)

        left_wrap = ttk.Frame(main_pane)
        right = ttk.Frame(main_pane)
        main_pane.add(left_wrap, weight=0)
        main_pane.add(right, weight=1)

        self.left_canvas = tk.Canvas(left_wrap, width=360, highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left_wrap, orient="vertical", command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=left_scrollbar.set)
        self.left_canvas.pack(side="left", fill="both", expand=True)
        left_scrollbar.pack(side="right", fill="y")

        left = ttk.Frame(self.left_canvas)
        left_window = self.left_canvas.create_window((0, 0), window=left, anchor="nw")

        def configure_left_scroll(_event=None):
            self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

        def configure_left_width(event):
            self.left_canvas.itemconfigure(left_window, width=event.width)

        left.bind("<Configure>", configure_left_scroll)
        self.left_canvas.bind("<Configure>", configure_left_width)
        self.left_canvas.bind("<Enter>", lambda _event: self.bind_all("<MouseWheel>", self.on_left_mousewheel))
        self.left_canvas.bind("<Leave>", lambda _event: self.unbind_all("<MouseWheel>"))

        left_tabs = ttk.Notebook(left)
        left_tabs.pack(fill="both", expand=True)
        setup_tab = ttk.Frame(left_tabs, padding=6)
        xfoil_tab = ttk.Frame(left_tabs, padding=6)
        export_tab = ttk.Frame(left_tabs, padding=6)
        left_tabs.add(setup_tab, text="Setup")
        left_tabs.add(xfoil_tab, text="XFOIL")
        left_tabs.add(export_tab, text="Export")

        # --- Folder controls ---
        folder_frame = self.make_collapsible(setup_tab, "Project", open_by_default=True)

        # Dropdown button
        action_btn = ttk.Menubutton(folder_frame, text="Actions", direction="below")
        action_btn.pack(fill="x", pady=(0, 10))

        action_menu = tk.Menu(action_btn, tearoff=0)
        action_btn["menu"] = action_menu

        action_menu.add_command(label="Save GUI settings", command=self.save_settings)
        action_menu.add_command(label="Save project...", command=self.save_project)
        action_menu.add_command(label="Load project...", command=self.load_project)
        action_menu.add_command(label="Save full project folder...", command=self.save_project_folder)
        action_menu.add_separator()
        action_menu.add_command(label="Choose airfoil folder...", command=self.choose_airfoil_folder)
        action_menu.add_command(label="Choose export folder...", command=self.choose_export_folder)
        action_menu.add_separator()
        action_menu.add_command(label="Download UIUC airfoil database ZIP", command=self.download_uiuc_database)
        action_menu.add_command(label="Refresh airfoil list", command=self._refresh_airfoil_dropdown)
        action_menu.add_separator()
        action_menu.add_command(label="Choose XFOIL executable...", command=self.choose_xfoil_exe)
        action_menu.add_separator()
        action_menu.add_command(label="Undo", command=self.undo)
        action_menu.add_command(label="Redo", command=self.redo)
        action_menu.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)

        # Info labels
        self.airfoil_dir_lbl = ttk.Label(folder_frame, text=f"Airfoil folder: {self.airfoil_dir}")
        self.airfoil_dir_lbl.pack(fill="x", pady=(5, 0))

        self.export_dir_lbl = ttk.Label(folder_frame, text=f"Export folder: {self.export_dir}")
        self.export_dir_lbl.pack(fill="x", pady=(5, 0))

        self.xfoil_lbl = ttk.Label(folder_frame, text="XFOIL: not selected")
        self.xfoil_lbl.pack(fill="x", pady=(5, 0))

        units_row = ttk.Frame(folder_frame)
        units_row.pack(fill="x", pady=(8, 0))
        ttk.Label(units_row, text="Units:").pack(side="left")
        self.unit_var = tk.StringVar(value="mm")
        ttk.Combobox(
            units_row,
            textvariable=self.unit_var,
            state="readonly",
            width=8,
            values=("mm", "cm", "m", "inch")
        ).pack(side="left", padx=(6, 0))

        # --- Add airfoil + settings ---
        add_frame = self.make_collapsible(setup_tab, "Airfoil & Geometry", open_by_default=True)

        ttk.Label(add_frame, text="Search:").grid(row=0, column=0, sticky="w")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(add_frame, textvariable=self.search_var, width=20)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=2)
        search_entry.bind("<KeyRelease>", self.filter_airfoils)

        ttk.Label(add_frame, text="Filter:").grid(row=1, column=0, sticky="w")
        self.search_filter_var = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(
            add_frame,
            textvariable=self.search_filter_var,
            state="readonly",
            width=18,
            values=("All", "Favorites", "NACA", "Symmetric NACA", "Cambered NACA", "Thin <=10%", "Medium 10-15%", "Thick >=15%")
        )
        filter_combo.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=2)
        filter_combo.bind("<<ComboboxSelected>>", self.filter_airfoils)

        ttk.Label(add_frame, text="Airfoil:").grid(row=2, column=0, sticky="w")
        self.airfoil_var = tk.StringVar()
        self.airfoil_combo = ttk.Combobox(
            add_frame,
            textvariable=self.airfoil_var,
            state="readonly",
            width=28
        )
        self.airfoil_combo.grid(row=2, column=1, sticky="ew", padx=(5, 0), pady=2)

        self.size_var = tk.StringVar(value="1.0")
        self.rx_var = tk.StringVar(value="0")
        self.ry_var = tk.StringVar(value="0")
        self.rz_var = tk.StringVar(value="0")
        self.ox_var = tk.StringVar(value="0")
        self.oy_var = tk.StringVar(value="0")
        self.oz_var = tk.StringVar(value="0")

        row = 3
        for label, var in [
            ("Size", self.size_var),
            ("RX", self.rx_var),
            ("RY", self.ry_var),
            ("RZ", self.rz_var),
            ("X", self.ox_var),
            ("Y", self.oy_var),
            ("Z", self.oz_var),
        ]:
            ttk.Label(add_frame, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(add_frame, textvariable=var, width=14)
            entry.grid(row=row, column=1, sticky="w", pady=2, padx=(5, 0))
            if not hasattr(self, "numeric_entries"):
                self.numeric_entries = []
            self.numeric_entries.append((entry, var))
            var.trace_add("write", self.schedule_live_preview)
            row += 1

        add_frame.columnconfigure(1, weight=1)

        btns = ttk.Frame(add_frame)
        btns.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Add", command=self.add_airfoil, style="Primary.TButton").pack(side="left", fill="x", expand=True)
        ttk.Button(btns, text="Apply", command=self.apply_to_selected, style="Secondary.TButton").pack(
            side="left", fill="x", expand=True, padx=6
        )

        tools = ttk.Frame(add_frame)
        tools.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(tools, text="Generate wing", command=self.generate_wing_template, style="Primary.TButton").pack(side="left", fill="x", expand=True)
        ttk.Button(tools, text="Analyze", command=self.update_geometry_stats, style="Secondary.TButton").pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

        tools2 = ttk.Frame(add_frame)
        tools2.grid(row=row + 2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(tools2, text="Blend checked", command=self.blend_airfoils_dialog, style="Secondary.TButton").pack(side="left", fill="x", expand=True)
        ttk.Button(tools2, text="Favorite", command=self.toggle_favorite, style="Secondary.TButton").pack(side="left", fill="x", expand=True, padx=(6, 0))

        # --- Polar controls ---
        polar_ctrl = self.make_collapsible(xfoil_tab, "Polar Settings", open_by_default=True)

        self.re_var = tk.StringVar(value="500000")
        self.mach_var = tk.StringVar(value="0.0")
        self.ncrit_var = tk.StringVar(value="9")
        self.alpha_start_var = tk.StringVar(value="-5")
        self.alpha_end_var = tk.StringVar(value="15")
        self.alpha_step_var = tk.StringVar(value="0.5")

        prow = 0
        for label, var in [
            ("Re", self.re_var),
            ("Mach", self.mach_var),
            ("Ncrit", self.ncrit_var),
            ("Alpha min", self.alpha_start_var),
            ("Alpha max", self.alpha_end_var),
            ("Alpha step", self.alpha_step_var),
        ]:
            ttk.Label(polar_ctrl, text=label + ":").grid(row=prow, column=0, sticky="w", pady=2)
            entry = ttk.Entry(polar_ctrl, textvariable=var, width=14)
            entry.grid(row=prow, column=1, sticky="w", pady=2, padx=(5, 0))
            self.numeric_entries.append((entry, var))
            prow += 1

        polar_ctrl.columnconfigure(1, weight=1)

        ttk.Button(
            polar_ctrl,
            text="Compute selected",
            command=self.compute_polar_selected
        ).grid(row=prow, column=0, columnspan=2, sticky="ew", pady=(8, 4))

        ttk.Button(
            polar_ctrl,
            text="Compute batch",
            command=self.compute_batch_polars
        ).grid(row=prow + 1, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        ttk.Button(
            polar_ctrl,
            text="Export CSV",
            command=self.export_current_polar_csv
        ).grid(row=prow + 2, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        ttk.Button(
            polar_ctrl,
            text="Export plot PNG",
            command=self.export_polar_plot_png
        ).grid(row=prow + 3, column=0, columnspan=2, sticky="ew")

        # --- Export controls ---
        export_frame = self.make_collapsible(export_tab, "Geometry Export", open_by_default=True)

        self.export_profile_var = tk.StringVar(value="Plain XYZ")
        ttk.Combobox(
            export_frame,
            textvariable=self.export_profile_var,
            state="readonly",
            values=("Plain XYZ", "SolidWorks Curve", "Fusion CSV", "OpenVSP DAT", "XFOIL DAT", "Mirrored Left/Right XYZ", "Wing Mesh OBJ", "Wing Mesh STL")
        ).pack(fill="x", pady=(0, 6))
        ttk.Button(export_frame, text="Delete selected", command=self.delete_selected).pack(fill="x", pady=(0, 6))
        ttk.Button(export_frame, text="Export selected geometry", command=self.export_selected).pack(fill="x",
                                                                                                     pady=(0, 6))
        ttk.Button(export_frame, text="Export ALL geometry", command=self.export_all).pack(fill="x")

        # --- Right side notebook ---
        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)

        tab3d = ttk.Frame(notebook)
        tabpolar = ttk.Frame(notebook)
        tabcompare = ttk.Frame(notebook)
        tabstats = ttk.Frame(notebook)
        tabscore = ttk.Frame(notebook)

        notebook.add(tab3d, text="3D Preview")
        notebook.add(tabpolar, text="Polar Plot")
        notebook.add(tabcompare, text="Compare")
        notebook.add(tabstats, text="Stats / Cleanup")
        notebook.add(tabscore, text="Polar Scores")

        workspace_toolbar = ttk.Frame(tab3d)
        workspace_toolbar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(workspace_toolbar, text="Add", command=self.add_airfoil, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(workspace_toolbar, text="Generate Wing", command=self.generate_wing_template, style="Primary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(workspace_toolbar, text="Blend Checked", command=self.blend_airfoils_dialog, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(workspace_toolbar, text="Export", command=self.export_all, style="Secondary.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(workspace_toolbar, text="Fit", command=self.reset_3d_zoom, style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(workspace_toolbar, text="Reset", command=self.reset_3d_zoom, style="Tool.TButton").pack(side="left", padx=(0, 10))
        ttk.Checkbutton(workspace_toolbar, text="Grid", variable=self.show_3d_grid, command=self._refresh_plot).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(workspace_toolbar, text="Axes", variable=self.show_3d_axes, command=self._refresh_plot).pack(side="left")

        preview_pane = ttk.PanedWindow(tab3d, orient="vertical")
        preview_pane.pack(fill="both", expand=True, padx=5, pady=5)

        # 3D figure
        plot_frame_3d = ttk.LabelFrame(preview_pane, text="3D Preview", padding=10)
        preview_pane.add(plot_frame_3d, weight=4)

        self.fig3d = Figure(figsize=(7, 5), dpi=100)
        self.ax3d = self.fig3d.add_subplot(111, projection="3d")
        self.ax3d.set_xlabel("X")
        self.ax3d.set_ylabel("Y")
        self.ax3d.set_zlabel("Z")

        self.canvas3d = FigureCanvasTkAgg(self.fig3d, master=plot_frame_3d)
        self.canvas3d.get_tk_widget().pack(fill="both", expand=True)
        self.canvas3d.mpl_connect("scroll_event", self.zoom_3d_plot)

        plot_buttons = ttk.Frame(tab3d)
        plot_buttons.pack(anchor="e", pady=(0, 8), padx=8)
        ttk.Button(plot_buttons, text="Refresh 3D preview", command=self._refresh_plot, style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(plot_buttons, text="Reset 3D zoom", command=self.reset_3d_zoom, style="Tool.TButton").pack(side="left")

        station_frame = ttk.LabelFrame(preview_pane, text="Stations", padding=8)
        preview_pane.add(station_frame, weight=1)
        station_toolbar = ttk.Frame(station_frame)
        station_toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(station_toolbar, text="Check selected", command=self.check_selected_rows, style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(station_toolbar, text="Uncheck all", command=self.uncheck_all_rows, style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(station_toolbar, text="Duplicate", command=self.duplicate_selected, style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(station_toolbar, text="Mirror Y", command=self.mirror_selected_y, style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(station_toolbar, text="Move up", command=lambda: self.move_selected(-1), style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(station_toolbar, text="Move down", command=lambda: self.move_selected(1), style="Tool.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(station_toolbar, text="Delete", command=self.delete_selected, style="Tool.TButton").pack(side="left")

        columns = ("use", "airfoil", "size", "rx", "ry", "rz", "ox", "oy", "oz")
        self.tree = ttk.Treeview(station_frame, columns=columns, show="headings", height=7, selectmode="extended")
        for c, w in zip(columns, [46, 170, 70, 70, 70, 70, 80, 80, 80]):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_row)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<space>", self.toggle_focused_check)
        station_scrollbar = ttk.Scrollbar(station_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=station_scrollbar.set)
        station_scrollbar.pack(side="right", fill="y")

        # Polar figure
        polar_plot_frame = ttk.LabelFrame(tabpolar, text="Polar Plot", padding=10)
        polar_plot_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.fig_polar = Figure(figsize=(7, 5), dpi=100)
        self.ax_polar = self.fig_polar.add_subplot(111)
        self.ax_polar.set_xlabel("Alpha [deg]")
        self.ax_polar.set_ylabel("CL")
        self.ax_polar.grid(True)

        self.canvas_polar = FigureCanvasTkAgg(self.fig_polar, master=polar_plot_frame)
        self.canvas_polar.get_tk_widget().pack(fill="both", expand=True)

        polar_bottom = ttk.Frame(tabpolar)
        polar_bottom.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Button(polar_bottom, text="Plot CL vs alpha", command=lambda: self.plot_polar_mode("cl_alpha")).pack(side="left", padx=(0, 6))
        ttk.Button(polar_bottom, text="Plot CD vs alpha", command=lambda: self.plot_polar_mode("cd_alpha")).pack(side="left", padx=(0, 6))
        ttk.Button(polar_bottom, text="Plot CL vs CD", command=lambda: self.plot_polar_mode("cl_cd")).pack(side="left", padx=(0, 6))
        ttk.Button(polar_bottom, text="Plot CM vs alpha", command=lambda: self.plot_polar_mode("cm_alpha")).pack(side="left", padx=(0, 6))

        self.polar_info_lbl = ttk.Label(tabpolar, text="No polar loaded.")
        self.polar_info_lbl.pack(anchor="w", padx=10, pady=(0, 10))

        compare_plot_frame = ttk.LabelFrame(tabcompare, text="Airfoil Shape Comparison", padding=10)
        compare_plot_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.fig_compare = Figure(figsize=(7, 5), dpi=100)
        self.ax_compare = self.fig_compare.add_subplot(111)
        self.ax_compare.set_aspect("equal", adjustable="box")
        self.ax_compare.grid(True)
        self.canvas_compare = FigureCanvasTkAgg(self.fig_compare, master=compare_plot_frame)
        self.canvas_compare.get_tk_widget().pack(fill="both", expand=True)
        compare_bottom = ttk.Frame(tabcompare)
        compare_bottom.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(compare_bottom, text="Compare selected shapes", command=self.compare_selected_shapes).pack(side="left", padx=(0, 6))
        ttk.Button(compare_bottom, text="Overlay selected polars", command=self.compare_selected_polars).pack(side="left")

        stats_frame = ttk.LabelFrame(tabstats, text="Selected Airfoil Geometry", padding=10)
        stats_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.stats_text = tk.Text(stats_frame, height=16, wrap="word")
        self.stats_text.pack(fill="both", expand=True)
        cleanup_frame = ttk.Frame(tabstats)
        cleanup_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.cleanup_mode_var = tk.StringVar(value="Normalize chord")
        ttk.Combobox(
            cleanup_frame,
            textvariable=self.cleanup_mode_var,
            state="readonly",
            values=("Normalize chord", "Repanel", "Close trailing edge", "Flip order", "Smooth", "Remove duplicates")
        ).pack(side="left", padx=(0, 6))
        ttk.Button(cleanup_frame, text="Apply cleanup as new airfoil", command=self.apply_cleanup_to_selected).pack(side="left")

        score_frame = ttk.LabelFrame(tabscore, text="Polar Performance Scores", padding=10)
        score_frame.pack(fill="both", expand=True, padx=5, pady=5)
        score_columns = ("airfoil", "max_cl", "stall_alpha", "min_cd", "best_ld", "best_ld_alpha", "zero_lift")
        self.score_tree = ttk.Treeview(score_frame, columns=score_columns, show="headings", height=14)
        for c, w in zip(score_columns, [150, 80, 90, 80, 90, 100, 90]):
            self.score_tree.heading(c, text=c)
            self.score_tree.column(c, width=w, anchor="center")
        self.score_tree.pack(fill="both", expand=True)
        score_buttons = ttk.Frame(tabscore)
        score_buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(score_buttons, text="Refresh scores", command=self.refresh_score_table).pack(side="left")

        self.status_var = tk.StringVar(value="Ready | stations: 0")
        ttk.Label(self, textvariable=self.status_var, anchor="w", style="Status.TLabel").pack(side="bottom", fill="x")
        self.bind_shortcuts()
        self.update_status("Ready")

    def on_left_mousewheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self.left_canvas.yview_scroll(delta * 3, "units")

    def update_status(self, message=None):
        if not hasattr(self, "status_var"):
            return
        selected = self.airfoil_var.get() if hasattr(self, "airfoil_var") else ""
        folder = self.export_dir if hasattr(self, "export_dir") else ""
        prefix = message or "Ready"
        self.status_var.set(
            f"{prefix} | selected: {selected or 'none'} | stations: {len(self.items)} | checked: {len(self.checked_items)} | export: {folder}"
        )

    def validate_numeric_inputs(self):
        ok = True
        for entry, var in getattr(self, "numeric_entries", []):
            try:
                float(var.get())
                entry.configure(style="TEntry")
            except Exception:
                entry.configure(style="Invalid.TEntry")
                ok = False
        return ok

    def bind_shortcuts(self):
        shortcuts = {
            "<Control-n>": self.shortcut_add_airfoil,
            "<Control-N>": self.shortcut_add_airfoil,
            "<Control-s>": lambda _event: self.save_project(),
            "<Control-S>": lambda _event: self.save_project(),
            "<Control-o>": lambda _event: self.load_project(),
            "<Control-O>": lambda _event: self.load_project(),
            "<Control-z>": lambda _event: self.undo(),
            "<Control-Z>": lambda _event: self.undo(),
            "<Control-y>": lambda _event: self.redo(),
            "<Control-Y>": lambda _event: self.redo(),
            "<Control-e>": lambda _event: self.export_all(),
            "<Control-E>": lambda _event: self.export_all(),
            "<Control-b>": lambda _event: self.blend_airfoils_dialog(),
            "<Control-B>": lambda _event: self.blend_airfoils_dialog(),
            "<Control-g>": lambda _event: self.generate_wing_template(),
            "<Control-G>": lambda _event: self.generate_wing_template(),
            "<Control-k>": lambda _event: self.check_selected_rows(),
            "<Control-K>": lambda _event: self.check_selected_rows(),
            "<Control-u>": lambda _event: self.uncheck_all_rows(),
            "<Control-U>": lambda _event: self.uncheck_all_rows(),
            "<Delete>": lambda _event: self.delete_selected(),
            "<F5>": lambda _event: self._refresh_plot(),
            "<F1>": lambda _event: self.show_shortcuts(),
        }
        for key, command in shortcuts.items():
            self.bind_all(key, command)

    def shortcut_add_airfoil(self, _event=None):
        self.add_airfoil()

    def show_shortcuts(self):
        messagebox.showinfo(
            "Keyboard shortcuts",
            "Ctrl+N  Add airfoil\n"
            "Ctrl+B  Blend two checked stations\n"
            "Ctrl+G  Generate wing\n"
            "Ctrl+K  Check highlighted rows\n"
            "Ctrl+U  Uncheck all rows\n"
            "Ctrl+E  Export all\n"
            "Ctrl+S  Save project\n"
            "Ctrl+O  Load project\n"
            "Ctrl+Z  Undo\n"
            "Ctrl+Y  Redo\n"
            "Delete  Delete selected rows\n"
            "Space  Toggle focused row checkbox\n"
            "F5  Refresh 3D preview\n"
            "F1  Show shortcuts"
        )

    # ---------- project files ----------

    def save_project(self):
        path = filedialog.asksaveasfilename(
            title="Save airfoil project",
            defaultextension=".json",
            filetypes=[("Airfoil project", "*.json"), ("JSON", "*.json")]
        )
        if not path:
            return

        project = {
            "version": 6,
            "airfoil_dir": str(self.airfoil_dir),
            "export_dir": str(self.export_dir),
            "xfoil_path": str(self.xfoil_path),
            "unit": self.unit_var.get(),
            "items": [
                {
                    **{k: v for k, v in it.items() if k != "id"},
                    "path": str(it["path"])
                }
                for it in self.items
            ]
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(project, f, indent=4)
            messagebox.showinfo("Project saved", f"Project saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def load_project(self):
        path = filedialog.askopenfilename(
            title="Load airfoil project",
            filetypes=[("Airfoil project", "*.json"), ("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                project = json.load(f)

            self.airfoil_dir = Path(project.get("airfoil_dir", str(self.airfoil_dir)))
            self.export_dir = Path(project.get("export_dir", str(self.export_dir)))
            self.xfoil_path = Path(project.get("xfoil_path", str(self.xfoil_path)))
            self.unit_var.set(project.get("unit", self.unit_var.get()))
            self.export_dir.mkdir(parents=True, exist_ok=True)

            self.airfoil_dir_lbl.config(text=f"Airfoil folder: {self.airfoil_dir}")
            self.export_dir_lbl.config(text=f"Export folder: {self.export_dir}")
            if str(self.xfoil_path):
                self.xfoil_lbl.config(text=f"XFOIL: {self.xfoil_path}")

            self.items.clear()
            self.checked_items.clear()
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self.item_counter = 0

            for saved in project.get("items", []):
                name = saved.get("name", "")
                path_obj = Path(saved.get("path", ""))
                if not path_obj.exists():
                    path_obj = self.get_airfoil_path_from_name(name) or path_obj
                item = {
                    "name": name,
                    "path": path_obj,
                    "size": safe_float(saved.get("size", 1.0), 1.0),
                    "rx": safe_float(saved.get("rx", 0.0), 0.0),
                    "ry": safe_float(saved.get("ry", 0.0), 0.0),
                    "rz": safe_float(saved.get("rz", 0.0), 0.0),
                    "ox": safe_float(saved.get("ox", 0.0), 0.0),
                    "oy": safe_float(saved.get("oy", 0.0), 0.0),
                    "oz": safe_float(saved.get("oz", 0.0), 0.0),
                }
                self.insert_item(item)

            self._refresh_airfoil_dropdown()
            self._refresh_plot()
            messagebox.showinfo("Project loaded", f"Loaded {len(self.items)} item(s).")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))

    def save_project_folder(self):
        folder = filedialog.askdirectory(title="Choose or create project folder")
        if not folder:
            return
        try:
            project_dir = Path(folder)
            project_dir.mkdir(parents=True, exist_ok=True)
            old_export = self.export_dir
            old_profile = self.export_profile_var.get()
            self.export_dir = project_dir / "exports"
            self.export_dir.mkdir(parents=True, exist_ok=True)
            self.project_folder = project_dir

            project_path = project_dir / "airfoil_project_v6.json"
            project = {
                "version": 6,
                "airfoil_dir": str(self.airfoil_dir),
                "export_dir": str(self.export_dir),
                "xfoil_path": str(self.xfoil_path),
                "unit": self.unit_var.get(),
                "items": [
                    {
                        **{k: v for k, v in it.items() if k != "id"},
                        "path": str(it["path"])
                    }
                    for it in self.items
                ],
                "favorites": sorted(self.favorites),
            }
            with open(project_path, "w", encoding="utf-8") as f:
                json.dump(project, f, indent=4)

            self.export_profile_var.set("Plain XYZ")
            self.export_items(self.items)
            self.export_dir = old_export
            self.export_profile_var.set(old_profile)
            self.export_dir_lbl.config(text=f"Export folder: {self.export_dir}")
            messagebox.showinfo("Project folder saved", f"Saved project package to:\n{project_dir}")
        except Exception as e:
            messagebox.showerror("Project folder failed", str(e))

    # ---------- folder pickers ----------

    def choose_airfoil_folder(self):
        folder = filedialog.askdirectory(title="Choose folder with airfoil .txt / .dat files")
        if folder:
            self.airfoil_dir = Path(folder)
            self.airfoil_dir_lbl.config(text=f"Airfoil folder: {self.airfoil_dir}")
            self._refresh_airfoil_dropdown()

    def choose_export_folder(self):
        folder = filedialog.askdirectory(title="Choose export folder")
        if folder:
            self.export_dir = Path(folder)
            self.export_dir.mkdir(parents=True, exist_ok=True)
            self.export_dir_lbl.config(text=f"Export folder: {self.export_dir}")

    def choose_xfoil_exe(self):
        file = filedialog.askopenfilename(
            title="Choose XFOIL executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        if file:
            self.xfoil_path = Path(file)
            self.xfoil_lbl.config(text=f"XFOIL: {self.xfoil_path}")

    # ---------- database download ----------

    def download_uiuc_database(self):
        try:
            target_dir = filedialog.askdirectory(title="Choose folder to extract UIUC database into")
            if not target_dir:
                return

            target_dir = Path(target_dir)
            zip_path = target_dir / "coord_seligFmt.zip"
            extract_dir = target_dir / "uiuc_airfoils"

            self.config(cursor="watch")
            self.update_idletasks()

            urllib.request.urlretrieve(UIUC_ZIP_URL, zip_path)

            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            self.airfoil_dir = extract_dir
            self.airfoil_dir_lbl.config(text=f"Airfoil folder: {self.airfoil_dir}")
            self._refresh_airfoil_dropdown()

            self.config(cursor="")
            messagebox.showinfo("Done", f"UIUC airfoil database downloaded and extracted to:\n{extract_dir}")
        except Exception as e:
            self.config(cursor="")
            messagebox.showerror("Download failed", str(e))

    # ---------- dropdown + table ----------

    def _refresh_airfoil_dropdown(self):
        files = get_airfoil_files(self.airfoil_dir)
        self.all_airfoils = [f.stem for f in files]

        if hasattr(self, "airfoil_combo"):
            self.airfoil_combo["values"] = self.all_airfoils

        if hasattr(self, "search_var"):
            self.filter_airfoils()
        elif self.all_airfoils:
            self.airfoil_var.set(self.all_airfoils[0])

        if not self.all_airfoils and hasattr(self, "airfoil_var"):
            self.airfoil_var.set("")

    def current_settings(self):
        self.validate_numeric_inputs()
        return dict(
            size=safe_float(self.size_var.get(), 1.0),
            rx=safe_float(self.rx_var.get(), 0.0),
            ry=safe_float(self.ry_var.get(), 0.0),
            rz=safe_float(self.rz_var.get(), 0.0),
            ox=safe_float(self.ox_var.get(), 0.0),
            oy=safe_float(self.oy_var.get(), 0.0),
            oz=safe_float(self.oz_var.get(), 0.0),
        )

    def insert_item(self, item):
        return self.insert_item_at(len(self.items), item)

    def insert_item_at(self, index, item):
        self.item_counter += 1
        item_id = f"item{self.item_counter}"
        item["id"] = item_id
        index = max(0, min(index, len(self.items)))
        self.items.insert(index, item)
        self.tree.insert("", index, iid=item_id, values=self.item_tree_values(item))
        self.update_status("Station added")
        return item_id

    def item_tree_values(self, item):
        mark = "[x]" if item["id"] in self.checked_items else "[ ]"
        return (
            mark, item["name"], item["size"], item["rx"], item["ry"],
            item["rz"], item["ox"], item["oy"], item["oz"]
        )

    def refresh_tree_row(self, iid):
        item = next((it for it in self.items if it["id"] == iid), None)
        if item and self.tree.exists(iid):
            self.tree.item(iid, values=self.item_tree_values(item))

    def checked_rows(self):
        ordered = list(self.tree.get_children())
        checked = [iid for iid in ordered if iid in self.checked_items]
        return [it for iid in checked for it in self.items if it["id"] == iid]

    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        column = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if region == "heading" and column == "#1":
            if len(self.checked_items) == len(self.items):
                self.uncheck_all_rows()
            else:
                self.check_all_rows()
            return "break"
        if region == "cell" and column == "#1" and iid:
            self.toggle_row_check(iid)
            return "break"
        return None

    def toggle_focused_check(self, _event=None):
        iid = self.tree.focus()
        if iid:
            self.toggle_row_check(iid)
        return "break"

    def toggle_row_check(self, iid):
        if iid in self.checked_items:
            self.checked_items.remove(iid)
        else:
            self.checked_items.add(iid)
        self.refresh_tree_row(iid)
        self.update_status("Checkbox selection updated")

    def check_selected_rows(self):
        for iid in self.tree.selection():
            self.checked_items.add(iid)
            self.refresh_tree_row(iid)
        self.update_status("Rows checked")

    def check_all_rows(self):
        self.checked_items = set(self.tree.get_children())
        for iid in self.tree.get_children():
            self.refresh_tree_row(iid)
        self.update_status("All rows checked")

    def uncheck_all_rows(self):
        self.checked_items.clear()
        for iid in self.tree.get_children():
            self.refresh_tree_row(iid)
        self.update_status("Rows unchecked")

    def snapshot_items(self):
        return [
            {
                k: (str(v) if k == "path" else v)
                for k, v in it.items()
                if k != "id"
            }
            for it in self.items
        ]

    def restore_items(self, snapshot):
        self.items.clear()
        self.checked_items.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.item_counter = 0
        for saved in snapshot:
            item = dict(saved)
            item["path"] = Path(item["path"])
            self.insert_item(item)
        self._refresh_plot()
        self.update_status("Restored")

    def push_undo(self):
        if hasattr(self, "tree"):
            self.undo_stack.append(self.snapshot_items())
            self.redo_stack.clear()
            if len(self.undo_stack) > 50:
                self.undo_stack.pop(0)

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self.snapshot_items())
        self.restore_items(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self.snapshot_items())
        self.restore_items(self.redo_stack.pop())

    def get_airfoil_path_from_name(self, name):
        txt_path = self.airfoil_dir / f"{name}.txt"
        dat_path = self.airfoil_dir / f"{name}.dat"

        if txt_path.exists():
            return txt_path
        if dat_path.exists():
            return dat_path
        return None

    def add_airfoil(self):
        name = self.airfoil_var.get().strip()
        if not name:
            messagebox.showerror("No airfoil", "No airfoil selected.")
            return

        path = self.get_airfoil_path_from_name(name)
        if path is None or not path.exists():
            messagebox.showerror("Missing file", f"File not found for airfoil: {name}")
            return

        self.push_undo()
        s = self.current_settings()
        self.insert_item({
            "name": name,
            "path": path,
            **s
        })

        self._refresh_plot()

    def on_select_row(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = next((it for it in self.items if it["id"] == iid), None)
        if not item:
            return

        self.loading_selection = True
        self.size_var.set(str(item["size"]))
        self.rx_var.set(str(item["rx"]))
        self.ry_var.set(str(item["ry"]))
        self.rz_var.set(str(item["rz"]))
        self.ox_var.set(str(item["ox"]))
        self.oy_var.set(str(item["oy"]))
        self.oz_var.set(str(item["oz"]))
        self.loading_selection = False
        self.update_geometry_stats(show_errors=False)
        self.update_status("Selection updated")

    def apply_to_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Select a row first.")
            return

        self.push_undo()
        s = self.current_settings()
        for iid in sel:
            for it in self.items:
                if it["id"] == iid:
                    it.update(s)
                    break
            self.refresh_tree_row(iid)

        self._refresh_plot()
        self.update_status("Settings applied")

    def schedule_live_preview(self, *args):
        if self.loading_selection or not hasattr(self, "tree"):
            return
        self.validate_numeric_inputs()
        if self.live_preview_after_id is not None:
            self.after_cancel(self.live_preview_after_id)
        self.live_preview_after_id = self.after(350, self.live_preview_selected)

    def live_preview_selected(self):
        self.live_preview_after_id = None
        sel = self.tree.selection()
        if not sel:
            return
        s = self.current_settings()
        for iid in sel:
            for it in self.items:
                if it["id"] == iid:
                    it.update(s)
                    self.refresh_tree_row(iid)
                    break
        self._refresh_plot()
        self.update_status("Preview updated")

    def duplicate_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.push_undo()
        new_ids = []
        for iid in sel:
            item = next((it for it in self.items if it["id"] == iid), None)
            if item:
                new_item = {k: v for k, v in item.items() if k != "id"}
                new_item["oy"] = safe_float(new_item["oy"], 0.0) + safe_float(new_item["size"], 1.0) * 0.1
                new_ids.append(self.insert_item(new_item))
        self.tree.selection_set(new_ids)
        self._refresh_plot()
        self.update_status("Station duplicated")

    def mirror_selected_y(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.push_undo()
        new_ids = []
        for iid in sel:
            item = next((it for it in self.items if it["id"] == iid), None)
            if item:
                new_item = {k: v for k, v in item.items() if k != "id"}
                new_item["oy"] = -safe_float(new_item["oy"], 0.0)
                new_item["rz"] = -safe_float(new_item["rz"], 0.0)
                new_ids.append(self.insert_item(new_item))
        self.tree.selection_set(new_ids)
        self._refresh_plot()
        self.update_status("Station mirrored")

    def move_selected(self, direction):
        sel = list(self.tree.selection())
        if not sel:
            return
        self.push_undo()
        order = list(self.tree.get_children())
        selected = set(sel)
        if direction < 0:
            rng = range(1, len(order))
        else:
            rng = range(len(order) - 2, -1, -1)
        for i in rng:
            j = i + direction
            if order[i] in selected and order[j] not in selected:
                order[i], order[j] = order[j], order[i]
        self.items = [next(it for it in self.items if it["id"] == iid) for iid in order]
        for index, iid in enumerate(order):
            self.tree.move(iid, "", index)
        self.tree.selection_set(sel)
        self.update_status("Stations reordered")

    def blend_airfoils_dialog(self):
        checked_ids = [iid for iid in self.tree.get_children() if iid in self.checked_items]
        if len(checked_ids) != 2:
            messagebox.showinfo("Choose two stations", "Check exactly two station rows, then click Blend Checked.")
            return
        item_a = next((it for it in self.items if it["id"] == checked_ids[0]), None)
        item_b = next((it for it in self.items if it["id"] == checked_ids[1]), None)
        if item_a is None or item_b is None:
            return

        count = simpledialog.askinteger(
            "Blend checked stations",
            "How many new airfoils should be inserted between the two checked stations?",
            initialvalue=3,
            minvalue=1,
            maxvalue=50
        )
        if not count:
            return

        out_dir = self.export_dir / "blended_airfoils"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.push_undo()

        order = list(self.tree.get_children())
        insert_at = min(order.index(checked_ids[0]), order.index(checked_ids[1])) + 1
        new_ids = []
        blend_keys = ("size", "rx", "ry", "rz", "ox", "oy", "oz")
        for i in range(count):
            t = (i + 1) / (count + 1)
            out_path = out_dir / (
                f"{sanitize_name(item_a['name'])}_to_{sanitize_name(item_b['name'])}_blend_{i + 1:02d}.dat"
            )
            blend_airfoil_files(item_a["path"], item_b["path"], out_path, t)
            blended_settings = {
                key: safe_float(item_a[key], 0.0) * (1.0 - t) + safe_float(item_b[key], 0.0) * t
                for key in blend_keys
            }
            new_ids.append(self.insert_item_at(insert_at + i, {
                "name": out_path.stem,
                "path": out_path,
                **blended_settings
            }))

        self.uncheck_all_rows()
        for iid in new_ids:
            self.checked_items.add(iid)
            self.refresh_tree_row(iid)
        self.tree.selection_set(new_ids)
        self._refresh_airfoil_dropdown()
        self._refresh_plot()
        self.update_status("Inserted blended stations")

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.push_undo()
        for iid in sel:
            self.tree.delete(iid)
            self.checked_items.discard(iid)
            self.items = [it for it in self.items if it["id"] != iid]
        self._refresh_plot()
        self.update_status("Station deleted")

    def generate_wing_template(self):
        name = self.airfoil_var.get().strip()
        if not name:
            messagebox.showerror("No airfoil", "Choose an airfoil first.")
            return
        path = self.get_airfoil_path_from_name(name)
        if path is None:
            messagebox.showerror("Missing file", f"File not found for airfoil: {name}")
            return

        self.push_undo()
        stations = simpledialog.askinteger("Wing generator", "Number of stations:", initialvalue=7, minvalue=2, maxvalue=101)
        if not stations:
            return
        span = simpledialog.askfloat("Wing generator", "Full span / Y width:", initialvalue=1000.0)
        root = simpledialog.askfloat("Wing generator", "Root chord / size:", initialvalue=safe_float(self.size_var.get(), 300.0))
        if span is None or root is None:
            return
        tip = simpledialog.askfloat("Wing generator", "Tip chord / size:", initialvalue=max(root * 0.4, 1.0))
        sweep = simpledialog.askfloat("Wing generator", "Tip sweep offset X:", initialvalue=0.0)
        dihedral = simpledialog.askfloat("Wing generator", "Tip dihedral offset Z:", initialvalue=0.0)
        twist_root = simpledialog.askfloat("Wing generator", "Root twist RY [deg]:", initialvalue=safe_float(self.ry_var.get(), 0.0))
        twist_tip = simpledialog.askfloat("Wing generator", "Tip twist RY [deg]:", initialvalue=twist_root)

        values = [span, root, tip, sweep, dihedral, twist_root, twist_tip]
        if any(v is None for v in values):
            return

        for i in range(stations):
            t = i / max(stations - 1, 1)
            side = -0.5 + t
            half_t = abs(side) * 2.0
            chord = root + (tip - root) * half_t
            ox = sweep * half_t
            oy = span * side
            oz = dihedral * half_t
            ry = twist_root + (twist_tip - twist_root) * half_t
            self.insert_item({
                "name": name,
                "path": path,
                "size": chord,
                "rx": safe_float(self.rx_var.get(), 0.0),
                "ry": ry,
                "rz": safe_float(self.rz_var.get(), 0.0),
                "ox": ox,
                "oy": oy,
                "oz": oz,
            })
        self._refresh_plot()

    def update_geometry_stats(self, show_errors=True):
        item = self.get_selected_item()
        if item is None:
            if hasattr(self, "stats_text"):
                self.stats_text.delete("1.0", "end")
                self.stats_text.insert("end", "Select one batch item to inspect its geometry.")
            return
        try:
            stats = analyze_airfoil_geometry(item["path"])
            text = (
                f"Airfoil: {item['name']}\n"
                f"File: {item['path']}\n\n"
                f"Point count: {stats['point_count']}\n"
                f"Chord: {stats['chord']:.6g}\n"
                f"Max thickness: {stats['max_thickness']:.6g} ({stats['max_thickness_pct']:.2f}%) at x={stats['max_thickness_x']:.4f}\n"
                f"Max camber: {stats['max_camber']:.6g} ({stats['max_camber_pct']:.2f}%) at x={stats['max_camber_x']:.4f}\n"
                f"Leading edge radius estimate: {stats['leading_edge_radius']:.6g}\n"
                f"Trailing edge gap: {stats['te_gap']:.6g}\n"
                f"Consecutive duplicate steps: {stats['duplicate_steps']}\n"
                f"Normalized 0..1 chord: {'yes' if stats['normalized'] else 'no'}\n"
                f"Malformed: {'yes' if stats['malformed'] else 'no'}\n"
            )
            self.stats_text.delete("1.0", "end")
            self.stats_text.insert("end", text)
        except Exception as e:
            if show_errors:
                messagebox.showerror("Analysis failed", str(e))

    def apply_cleanup_to_selected(self):
        item = self.get_selected_item()
        if item is None:
            messagebox.showinfo("Nothing selected", "Select one batch item first.")
            return
        mode = self.cleanup_mode_var.get()
        n_points = 160
        if mode == "Repanel":
            n_points = simpledialog.askinteger("Repanel", "Number of output points:", initialvalue=160, minvalue=10, maxvalue=2000)
            if not n_points:
                return
        try:
            self.push_undo()
            clean_dir = self.export_dir / "cleaned_airfoils"
            out_name = f"{sanitize_name(item['name'])}_{sanitize_name(mode.lower().replace(' ', '_'))}.dat"
            out_path = clean_dir / out_name
            cleanup_airfoil_file(item["path"], out_path, mode, n_points=n_points)
            new_item = {**item, "name": out_path.stem, "path": out_path}
            new_item.pop("id", None)
            iid = self.insert_item(new_item)
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self._refresh_plot()
            self.update_geometry_stats(show_errors=False)
            messagebox.showinfo("Cleanup done", f"Created cleaned airfoil:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Cleanup failed", str(e))

    def compare_selected_shapes(self):
        sel = self.tree.selection()
        chosen = [it for it in self.items if it["id"] in sel]
        if not chosen:
            chosen = self.items[:5]
        self.ax_compare.clear()
        for it in chosen[:8]:
            try:
                x, _, z = load_airfoil_xz(it["path"])
                self.ax_compare.plot(x, z, linewidth=1.2, label=it["name"])
            except Exception:
                pass
        self.ax_compare.set_xlabel("x / chord")
        self.ax_compare.set_ylabel("z / chord")
        self.ax_compare.set_aspect("equal", adjustable="box")
        self.ax_compare.grid(True)
        self.ax_compare.legend(loc="best", fontsize=8)
        self.canvas_compare.draw()

    def compare_selected_polars(self):
        sel = self.tree.selection()
        names = [it["name"] for it in self.items if it["id"] in sel]
        if not names:
            names = list(self.polar_results.keys())
        self.ax_compare.clear()
        for name in names[:8]:
            polar = self.polar_results.get(name)
            if polar is not None:
                self.ax_compare.plot(polar["cd"], polar["cl"], linewidth=1.2, label=name)
        self.ax_compare.set_xlabel("CD")
        self.ax_compare.set_ylabel("CL")
        self.ax_compare.set_aspect("auto")
        self.ax_compare.grid(True)
        self.ax_compare.legend(loc="best", fontsize=8)
        self.canvas_compare.draw()

    def refresh_score_table(self):
        if not hasattr(self, "score_tree"):
            return
        for iid in self.score_tree.get_children():
            self.score_tree.delete(iid)
        for name, polar in sorted(self.polar_results.items()):
            try:
                score = polar_score(polar)
                self.score_tree.insert("", "end", values=(
                    name,
                    f"{score['max_cl']:.3f}",
                    f"{score['stall_alpha']:.2f}",
                    f"{score['min_cd']:.5f}",
                    f"{score['best_ld']:.1f}",
                    f"{score['best_ld_alpha']:.2f}",
                    f"{score['zero_lift_alpha']:.2f}" if np.isfinite(score["zero_lift_alpha"]) else "n/a",
                ))
            except Exception:
                pass

    # ---------- geometry export ----------

    def build_outname(self, it):
        ext = ".csv" if self.export_profile_var.get() == "Fusion CSV" else ".dat" if self.export_profile_var.get() in ("OpenVSP DAT", "XFOIL DAT") else ".txt"
        return (
            f"{it['name']}"
            f"_s{it['size']:g}"
            f"_tx{it['rx']:g}_ty{it['ry']:g}_tz{it['rz']:g}"
            f"_ox{it['ox']:g}_oy{it['oy']:g}_oz{it['oz']:g}{ext}"
        )

    def export_geometry_profile(self, outpath, it, x, y, z):
        profile = self.export_profile_var.get()
        if profile == "Plain XYZ":
            export_xyz(outpath, x, y, z)
        elif profile == "SolidWorks Curve":
            with open(outpath, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                for row in zip(x, y, z):
                    writer.writerow([f"{v:.6f}" for v in row])
        elif profile == "Fusion CSV":
            with open(outpath, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["x", "y", "z"])
                for row in zip(x, y, z):
                    writer.writerow([f"{v:.6f}" for v in row])
        elif profile == "OpenVSP DAT":
            with open(outpath, "w", encoding="utf-8") as f:
                f.write(f"{it['name']}\n")
                for xi, zi in zip(x, z):
                    f.write(f"{xi:.6f} {zi:.6f}\n")
        elif profile == "XFOIL DAT":
            with open(outpath, "w", encoding="utf-8") as f:
                f.write(f"{it['name']}\n")
                for xi, zi in zip(x, z):
                    f.write(f"{xi:.6f} {zi:.6f}\n")
        elif profile == "Mirrored Left/Right XYZ":
            stem = outpath.with_suffix("")
            export_xyz(stem.with_name(stem.name + "_R.txt"), x, y, z)
            export_xyz(stem.with_name(stem.name + "_L.txt"), x, -y, z)
        else:
            export_xyz(outpath, x, y, z)

    def export_items(self, items):
        if not items:
            messagebox.showinfo("Nothing to export", "No airfoils selected.")
            return

        profile = self.export_profile_var.get()
        if profile in ("Wing Mesh OBJ", "Wing Mesh STL"):
            self.export_wing_mesh(items, profile)
            return

        exported = 0
        errors = []

        for it in items:
            try:
                x, y, z = load_airfoil_xz(it["path"])
                x2, y2, z2 = transform_points(
                    x, y, z,
                    it["size"], it["rx"], it["ry"], it["rz"],
                    it["ox"], it["oy"], it["oz"]
                )
                scale = unit_factor(self.unit_var.get())
                x2, y2, z2 = x2 * scale, y2 * scale, z2 * scale
                outname = self.build_outname(it)
                outpath = self.export_dir / outname
                self.export_geometry_profile(outpath, it, x2, y2, z2)
                exported += 1
            except Exception as e:
                errors.append(f"{it['name']}: {e}")

        if errors:
            messagebox.showwarning("Export finished with errors", "\n".join(errors))
        else:
            messagebox.showinfo("Export done", f"Exported {exported} file(s) to:\n{self.export_dir}")

    def export_wing_mesh(self, items, profile):
        if len(items) < 2:
            messagebox.showinfo("Need stations", "Wing mesh export needs at least two stations.")
            return
        ext = ".obj" if profile == "Wing Mesh OBJ" else ".stl"
        path = filedialog.asksaveasfilename(
            title=f"Save {profile}",
            defaultextension=ext,
            initialfile=f"wing_mesh{ext}",
            filetypes=[("OBJ mesh", "*.obj")] if ext == ".obj" else [("STL mesh", "*.stl")]
        )
        if not path:
            return
        try:
            vertices, faces = triangulated_wing_mesh(items, unit_scale=unit_factor(self.unit_var.get()))
            if profile == "Wing Mesh OBJ":
                write_obj(Path(path), vertices, faces)
            else:
                write_ascii_stl(Path(path), vertices, faces)
            messagebox.showinfo("Mesh exported", f"Exported {len(vertices)} vertices and {len(faces)} faces to:\n{path}")
        except Exception as e:
            messagebox.showerror("Mesh export failed", str(e))

    def export_selected(self):
        chosen = self.checked_rows()
        if not chosen:
            sel = self.tree.selection()
            chosen = [it for it in self.items if it["id"] in sel]
        self.export_items(chosen)

    def export_all(self):
        self.export_items(self.items)

    # ---------- XFOIL polar ----------

    def get_selected_item(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        return next((it for it in self.items if it["id"] == iid), None)

    def compute_polar_selected(self):
        item = self.get_selected_item()
        if item is None:
            messagebox.showinfo("Nothing selected", "Select one airfoil in the batch list first.")
            return

        if not self.xfoil_path or not self.xfoil_path.exists():
            messagebox.showerror("Missing XFOIL", "Please choose your XFOIL executable first.")
            return

        reynolds = safe_float(self.re_var.get(), 500000)
        mach = safe_float(self.mach_var.get(), 0.0)
        ncrit = safe_int(self.ncrit_var.get(), 9)
        alpha_start = safe_float(self.alpha_start_var.get(), -5)
        alpha_end = safe_float(self.alpha_end_var.get(), 15)
        alpha_step = safe_float(self.alpha_step_var.get(), 0.5)

        try:
            self.config(cursor="watch")
            self.update_idletasks()

            polar = run_xfoil_polar_retry(
                self.xfoil_path,
                item["path"],
                reynolds=reynolds,
                mach=mach,
                ncrit=ncrit,
                alpha_start=alpha_start,
                alpha_end=alpha_end,
                alpha_step=alpha_step
            )

            self.current_polar = polar
            self.current_polar_name = item["name"]
            self.polar_results[item["name"]] = polar
            self.refresh_score_table()

            self.plot_polar_mode("cl_alpha")
            self.polar_info_lbl.config(
                text=(
                    f"Loaded polar: {item['name']}    "
                    f"Re={reynolds:g}    Mach={mach:g}    Ncrit={ncrit}    "
                    f"alpha={alpha_start:g}..{alpha_end:g} step {alpha_step:g}    "
                    f"{polar_summary(polar)}"
                )
            )

            self.config(cursor="")
        except Exception as e:
            self.config(cursor="")
            messagebox.showerror("XFOIL failed", str(e))

    def polar_settings(self):
        return {
            "reynolds": safe_float(self.re_var.get(), 500000),
            "mach": safe_float(self.mach_var.get(), 0.0),
            "ncrit": safe_int(self.ncrit_var.get(), 9),
            "alpha_start": safe_float(self.alpha_start_var.get(), -5),
            "alpha_end": safe_float(self.alpha_end_var.get(), 15),
            "alpha_step": safe_float(self.alpha_step_var.get(), 0.5),
        }

    def compute_batch_polars(self):
        sel = self.tree.selection()
        chosen = [it for it in self.items if it["id"] in sel] if sel else self.items
        if not chosen:
            messagebox.showinfo("Nothing selected", "Add or select airfoils first.")
            return
        if not self.xfoil_path or not self.xfoil_path.exists():
            messagebox.showerror("Missing XFOIL", "Please choose your XFOIL executable first.")
            return

        settings = self.polar_settings()
        out_dir = self.export_dir / "polars"
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = 0
        errors = []
        try:
            self.config(cursor="watch")
            self.update_idletasks()
            for item in chosen:
                try:
                    polar = run_xfoil_polar_retry(self.xfoil_path, item["path"], **settings)
                    self.polar_results[item["name"]] = polar
                    self.current_polar = polar
                    self.current_polar_name = item["name"]
                    fname = (
                        f"{sanitize_name(item['name'])}"
                        f"_Re{settings['reynolds']:g}_M{settings['mach']:g}_N{settings['ncrit']}"
                        f"_a{settings['alpha_start']:g}_{settings['alpha_end']:g}_{settings['alpha_step']:g}.csv"
                    )
                    save_polar_csv(out_dir / fname, polar)
                    ok += 1
                    self.polar_info_lbl.config(text=f"Computed {ok}/{len(chosen)}: {item['name']}    {polar_summary(polar)}")
                    self.update_idletasks()
                except Exception as e:
                    errors.append(f"{item['name']}: {e}")
            if self.current_polar is not None:
                self.plot_polar_mode("cl_alpha")
                self.refresh_score_table()
            self.config(cursor="")
            if errors:
                messagebox.showwarning("Batch polars finished", f"Computed {ok} polar(s). Errors:\n" + "\n".join(errors[:12]))
            else:
                messagebox.showinfo("Batch polars done", f"Computed and exported {ok} polar CSV file(s) to:\n{out_dir}")
        except Exception as e:
            self.config(cursor="")
            messagebox.showerror("Batch failed", str(e))

    def export_current_polar_csv(self):
        if self.current_polar is None:
            messagebox.showinfo("No polar", "Compute a polar first.")
            return

        settings = self.polar_settings()
        default_name = (
            f"{sanitize_name(self.current_polar_name)}"
            f"_Re{settings['reynolds']:g}_M{settings['mach']:g}_N{settings['ncrit']}"
            f"_a{settings['alpha_start']:g}_{settings['alpha_end']:g}_{settings['alpha_step']:g}.csv"
        )
        csv_path = filedialog.asksaveasfilename(
            title="Save polar CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv")]
        )
        if not csv_path:
            return

        try:
            save_polar_csv(Path(csv_path), self.current_polar)
            messagebox.showinfo("Saved", f"Polar CSV saved to:\n{csv_path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def export_polar_plot_png(self):
        if self.current_polar is None:
            messagebox.showinfo("No polar", "Compute a polar first.")
            return
        default_name = f"{sanitize_name(self.current_polar_name)}_polar_plot.png"
        path = filedialog.asksaveasfilename(
            title="Save polar plot PNG",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG image", "*.png")]
        )
        if not path:
            return
        try:
            self.fig_polar.savefig(path, dpi=180, bbox_inches="tight")
            messagebox.showinfo("Saved", f"Polar plot saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def plot_polar_mode(self, mode="cl_alpha"):
        self.ax_polar.clear()

        if self.current_polar is None:
            self.ax_polar.set_title("No polar loaded")
            self.ax_polar.grid(True)
            self.canvas_polar.draw()
            return

        p = self.current_polar

        if mode == "cl_alpha":
            self.ax_polar.plot(p["alpha"], p["cl"], linewidth=1.5)
            idx = int(np.argmax(p["cl"]))
            self.ax_polar.scatter([p["alpha"][idx]], [p["cl"][idx]], s=35)
            self.ax_polar.set_xlabel("Alpha [deg]")
            self.ax_polar.set_ylabel("CL")
            self.ax_polar.set_title(f"{self.current_polar_name}: CL vs alpha")
        elif mode == "cd_alpha":
            self.ax_polar.plot(p["alpha"], p["cd"], linewidth=1.5)
            self.ax_polar.set_xlabel("Alpha [deg]")
            self.ax_polar.set_ylabel("CD")
            self.ax_polar.set_title(f"{self.current_polar_name}: CD vs alpha")
        elif mode == "cl_cd":
            self.ax_polar.plot(p["cd"], p["cl"], linewidth=1.5)
            valid = p["cd"] > 0
            if np.any(valid):
                ld = np.where(valid, p["cl"] / p["cd"], np.nan)
                idx = int(np.nanargmax(ld))
                self.ax_polar.scatter([p["cd"][idx]], [p["cl"][idx]], s=35)
            self.ax_polar.set_xlabel("CD")
            self.ax_polar.set_ylabel("CL")
            self.ax_polar.set_title(f"{self.current_polar_name}: CL vs CD")
        elif mode == "cm_alpha":
            self.ax_polar.plot(p["alpha"], p["cm"], linewidth=1.5)
            self.ax_polar.set_xlabel("Alpha [deg]")
            self.ax_polar.set_ylabel("CM")
            self.ax_polar.set_title(f"{self.current_polar_name}: CM vs alpha")

        self.ax_polar.grid(True)
        self.canvas_polar.draw()

    # ---------- 3D plot ----------

    def zoom_3d_plot(self, event):
        if event.inaxes != self.ax3d:
            return
        scale = 0.82 if event.button == "up" else 1.22
        for getter, setter in [
            (self.ax3d.get_xlim3d, self.ax3d.set_xlim3d),
            (self.ax3d.get_ylim3d, self.ax3d.set_ylim3d),
            (self.ax3d.get_zlim3d, self.ax3d.set_zlim3d),
        ]:
            lo, hi = getter()
            center = (lo + hi) / 2.0
            half = (hi - lo) * scale / 2.0
            setter(center - half, center + half)
        self.canvas3d.draw_idle()

    def reset_3d_zoom(self):
        self._refresh_plot()

    def _refresh_plot(self):
        self.ax3d.clear()
        if self.show_3d_axes.get():
            self.ax3d.set_xlabel("X")
            self.ax3d.set_ylabel("Y")
            self.ax3d.set_zlabel("Z")
        else:
            self.ax3d.set_axis_off()
        self.ax3d.grid(self.show_3d_grid.get())

        if not self.items:
            self.ax3d.set_axis_off()
            self.ax3d.text2D(0.5, 0.5, "No stations added", transform=self.ax3d.transAxes, ha="center", va="center", fontsize=14)
            self.ax3d.set_xticks([])
            self.ax3d.set_yticks([])
            self.ax3d.set_zticks([])
            self.ax3d.set_xlim(0, 1)
            self.ax3d.set_ylim(0, 1)
            self.ax3d.set_zlim(0, 1)
            self.canvas3d.draw()
            self.update_status("Ready")
            return

        for it in self.items:
            try:
                x, y, z = load_airfoil_xz(it["path"])
                x2, y2, z2 = transform_points(
                    x, y, z,
                    it["size"], it["rx"], it["ry"], it["rz"],
                    it["ox"], it["oy"], it["oz"]
                )
                self.ax3d.plot(x2, y2, z2, linewidth=1.2, label=it["name"])
            except Exception:
                pass

        lines = self.ax3d.get_lines()
        if lines:
            xs_list, ys_list, zs_list = [], [], []

            for ln in lines:
                if hasattr(ln, "get_data_3d"):
                    xi, yi, zi = ln.get_data_3d()
                else:
                    xi, yi = ln.get_data()
                    zi = ln._verts3d[2] if hasattr(ln, "_verts3d") else np.zeros_like(xi)

                xs_list.append(np.asarray(xi))
                ys_list.append(np.asarray(yi))
                zs_list.append(np.asarray(zi))

            xs = np.concatenate(xs_list)
            ys = np.concatenate(ys_list)
            zs = np.concatenate(zs_list)

            xmin, xmax = xs.min(), xs.max()
            ymin, ymax = ys.min(), ys.max()
            zmin, zmax = zs.min(), zs.max()

            xmid = (xmin + xmax) / 2
            ymid = (ymin + ymax) / 2
            zmid = (zmin + zmax) / 2

            max_range = max(xmax - xmin, ymax - ymin, zmax - zmin)
            if max_range <= 0:
                max_range = 1.0

            self.ax3d.set_xlim(xmid - max_range / 2, xmid + max_range / 2)
            self.ax3d.set_ylim(ymid - max_range / 2, ymid + max_range / 2)
            self.ax3d.set_zlim(zmid - max_range / 2, zmid + max_range / 2)
            self.ax3d.set_box_aspect([1, 1, 1])

        self.ax3d.view_init(elev=18, azim=-62)
        if len(self.items) <= 12:
            self.ax3d.legend(loc="upper right", fontsize=8)
        self.canvas3d.draw()
        self.update_status("3D preview refreshed")


if __name__ == "__main__":
    app = AirfoilApp()
    app.mainloop()
