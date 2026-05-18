#!/usr/bin/env python3
"""
011 - Integrates with MU110N
Single-file mod manager with UI
"""

import os, sys, json, shutil, zipfile, subprocess, webbrowser, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

GAME_EXE = "Sheepy.exe"
GAME_HTML = "index.html"
MODS_DIR = "Mods"
BACKUP_DIR = "Original_Backup"
CONFIG_FILE = "mod_config.json"

class SheepyModLoader:
    def __init__(self, game_path):
        self.game_path = Path(game_path)
        self.mods_path = self.game_path / MODS_DIR
        self.backup_path = self.game_path / BACKUP_DIR
        self.config_file = self.mods_path / CONFIG_FILE
        self._ensure_dirs()

    def _ensure_dirs(self):
        for sub in ["Active", "Disabled"]:
            (self.mods_path / sub).mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(exist_ok=True)
        if not self.config_file.exists():
            self._save_config({"active_mods": [], "load_order": []})

    def _load_config(self):
        with open(self.config_file, 'r') as f:
            return json.load(f)

    def _save_config(self, cfg):
        with open(self.config_file, 'w') as f:
            json.dump(cfg, f, indent=2)

    def get_all_mods(self):
        mods = []
        for status in ["Active", "Disabled"]:
            folder = self.mods_path / status
            if not folder.exists(): continue
            for mod_dir in sorted(folder.iterdir()):
                if mod_dir.is_dir():
                    info = self._read_mod_info(mod_dir)
                    info["status"] = status
                    info["folder"] = str(mod_dir)
                    mods.append(info)
        return mods

    def _read_mod_info(self, mod_dir):
        mod_json = mod_dir / "mod.json"
        default = {"name": mod_dir.name, "version": "?", "author": "Unknown",
                   "description": "No description", "priority": 50}
        if mod_json.exists():
            try:
                with open(mod_json, 'r') as f:
                    default.update(json.load(f))
            except: pass
        return default

    def install_mod(self, archive_path):
        src = Path(archive_path)
        name = src.stem
        target = self.mods_path / "Disabled" / name
        counter, original_name = 1, name
        while target.exists():
            name = f"{original_name}_{counter}"
            target = self.mods_path / "Disabled" / name
            counter += 1
        if src.is_file() and src.suffix.lower() == '.zip':
            with zipfile.ZipFile(src, 'r') as z:
                z.extractall(target)
        elif src.is_dir():
            shutil.copytree(src, target)
        else:
            raise ValueError("Must be a .zip file or folder")
        return name

    def toggle_mod(self, mod_name, current_status):
        src = self.mods_path / current_status / mod_name
        dst_status = "Disabled" if current_status == "Active" else "Active"
        dst = self.mods_path / dst_status / mod_name
        if dst.exists():
            raise FileExistsError(f"Name conflict in {dst_status}")
        shutil.move(str(src), str(dst))
        cfg = self._load_config()
        if dst_status == "Active":
            if mod_name not in cfg["active_mods"]:
                cfg["active_mods"].append(mod_name)
        else:
            cfg["active_mods"] = [m for m in cfg["active_mods"] if m != mod_name]
        self._save_config(cfg)
        return dst_status

    def delete_mod(self, mod_name, status):
        target = self.mods_path / status / mod_name
        if target.exists():
            shutil.rmtree(target)
        cfg = self._load_config()
        cfg["active_mods"] = [m for m in cfg["active_mods"] if m != mod_name]
        self._save_config(cfg)

    def apply_mods(self):
        self.restore_originals()
        active_dir = self.mods_path / "Active"
        if not active_dir.exists():
            return []
        mods = []
        for mod_dir in active_dir.iterdir():
            if mod_dir.is_dir():
                info = self._read_mod_info(mod_dir)
                info["_path"] = mod_dir
                mods.append(info)
        mods.sort(key=lambda m: m.get("priority", 50))
        applied = []
        for mod in mods:
            try:
                self._inject_mod(mod)
                applied.append(mod["name"])
            except Exception as e:
                applied.append(f"{mod['name']} (ERROR: {e})")
        return applied

    def _inject_mod(self, mod_info):
        mod_path = mod_info["_path"]
        for mod_file, game_file in mod_info.get("file_mappings", {}).items():
            src, dst = mod_path / mod_file, self.game_path / game_file
            if src.exists():
                self._backup_file(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        patches = mod_info.get("data_patches", [])
        if patches:
            data_file = self.game_path / "data.json"
            if data_file.exists():
                self._backup_file(data_file)
                self._apply_json_patches(data_file, patches)

    def _backup_file(self, filepath):
        if not filepath.exists(): return
        rel = filepath.relative_to(self.game_path)
        backup = self.backup_path / rel
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filepath, backup)

    def _apply_json_patches(self, filepath, patches):
        with open(filepath, 'r') as f:
            data = json.load(f)
        for patch in patches:
            op, path = patch.get("operation", "replace"), patch["path"].split(".")
            value = patch["value"]
            current = data
            for key in path[:-1]:
                if key not in current: current[key] = {}
                current = current[key]
            if op in ("replace", "replace_value"):
                current[path[-1]] = value
            elif op == "add":
                if isinstance(current.get(path[-1]), list):
                    current[path[-1]].append(value)
                else:
                    current[path[-1]] = value
            elif op == "remove":
                current.pop(path[-1], None)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def restore_originals(self):
        if not self.backup_path.exists(): return
        for backup_file in self.backup_path.rglob("*"):
            if backup_file.is_file():
                rel = backup_file.relative_to(self.backup_path)
                original = self.game_path / rel
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, original)

    def launch_game(self):
        exe = self.game_path / GAME_EXE
        if exe.exists():
            subprocess.Popen([str(exe)], cwd=str(self.game_path))
            return "desktop"
        html = self.game_path / GAME_HTML
        if html.exists():
            webbrowser.open(str(html.resolve()))
            return "web"
        return None

class ModLoaderUI:
    def __init__(self, root):
        self.root = root
        self.root.title(" 011")
        self.root.geometry("900x650")
        self.root.minsize(750, 500)
        self.style = ttk.Style()
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        self.loader = None
        self.mod_list = []
        self.selected_mod = None
        self._build_ui()
        self._scan_for_game()

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text=" 011", style="Header.TLabel").pack(side="left")

        ttk.Button(top, text=" Open MU110N", command=self._open_mod_maker).pack(side="right", padx=5)
        ttk.Button(top, text=" Set Game Folder", command=self._browse_game).pack(side="right", padx=5)
        ttk.Button(top, text=" Launch Game", command=self._launch).pack(side="right", padx=5)

        self.path_var = tk.StringVar(value="No game folder selected")
        ttk.Label(self.root, textvariable=self.path_var, style="Sub.TLabel", foreground="gray").pack(padx=10, anchor="w")
        ttk.Separator(self.root, orient="horizontal").pack(fill="x", pady=5)

        # Main content
        content = ttk.Frame(self.root)
        content.pack(fill="both", expand=True, padx=10, pady=5)

        # Left: Mod list
        left = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Installed Mods", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 5))

        columns = ("status", "version", "priority")
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings", height=15)
        self.tree.heading("#0", text="Mod Name")
        self.tree.heading("status", text="Status")
        self.tree.heading("version", text="Version")
        self.tree.heading("priority", text="Priority")
        self.tree.column("#0", width=250)
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("version", width=80, anchor="center")
        self.tree.column("priority", width=60, anchor="center")

        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._toggle_selected())

        # Right: Details & Actions
        right = ttk.Frame(content, width=300)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        ttk.Label(right, text="Actions", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        btn_frame = ttk.Frame(right)
        btn_frame.pack(fill="x", pady=5)
        ttk.Button(btn_frame, text=" Install Mod", command=self._install_mod).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text=" Enable/Disable", command=self._toggle_selected).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text=" Delete", command=self._delete_selected).pack(fill="x", pady=2)

        ttk.Separator(right, orient="horizontal").pack(fill="x", pady=10)

        ttk.Label(right, text="Mod Details", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        self.details_text = tk.Text(right, wrap="word", height=12, state="disabled", bg="#f5f5f5")
        self.details_text.pack(fill="both", expand=True)

        # Bottom bar
        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left")
        ttk.Button(bottom, text=" Apply Mods", command=self._apply_mods).pack(side="right", padx=5)
        ttk.Button(bottom, text="↩ Restore Originals", command=self._restore).pack(side="right", padx=5)

    def _open_mod_maker(self):
        """Launch the separate MU110N tool"""
        maker_path = Path(__file__).parent / "MU110N.py"
        if not maker_path.exists():
            # Try same directory
            maker_path = Path("MU110N.py")

        if maker_path.exists():
            try:
                subprocess.Popen([sys.executable, str(maker_path)])
                self.status_var.set(" MU110N launched")
            except Exception as e:
                messagebox.showerror("Error", f"Could not launch MU110N:\n{e}")
        else:
            messagebox.showinfo("MU110N Not Found",
                                "MU110N.py not found.\n\n"
                                "Make sure it's in the same folder as this mod loader.")

    def _scan_for_game(self):
        guesses = [Path("."), Path.home() / "Games" / "Sheepy",
                   Path("C:/Games/Sheepy"),
                   Path("C:/Program Files (x86)/Steam/steamapps/common/Sheepy")]
        for path in guesses:
            if (path / GAME_EXE).exists() or (path / GAME_HTML).exists():
                self._set_game_path(path)
                return

    def _browse_game(self):
        folder = filedialog.askdirectory(title="Select Sheepy Game Folder")
        if folder:
            self._set_game_path(Path(folder))

    def _set_game_path(self, path):
        if not (path / GAME_EXE).exists() and not (path / GAME_HTML).exists():
            messagebox.showwarning("Game Not Found", f"Could not find {GAME_EXE} or {GAME_HTML} in:\n{path}")
            return
        self.loader = SheepyModLoader(path)
        self.path_var.set(str(path.resolve()))
        self._refresh_mod_list()
        self.status_var.set(f"Game folder loaded: {path.name}")

    def _refresh_mod_list(self):
        if not self.loader: return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.mod_list = self.loader.get_all_mods()
        for mod in self.mod_list:
            tag = "active" if mod["status"] == "Active" else "disabled"
            self.tree.insert("", "end", text=mod["name"], values=(
                " Active" if mod["status"] == "Active" else " Disabled",
                mod.get("version", "?"), mod.get("priority", 50)
            ), tags=(tag,))
        self.tree.tag_configure("active", foreground="green")
        self.tree.tag_configure("disabled", foreground="gray")

    def _on_select(self, event):
        selection = self.tree.selection()
        if not selection: return
        idx = self.tree.index(selection[0])
        if idx < len(self.mod_list):
            mod = self.mod_list[idx]
            self.selected_mod = mod
            self._show_details(mod)

    def _show_details(self, mod):
        self.details_text.config(state="normal")
        self.details_text.delete("1.0", "end")
        info = f"""Name: {mod['name']}
Status: {mod['status']}
Version: {mod.get('version', '?')}
Author: {mod.get('author', 'Unknown')}
Priority: {mod.get('priority', 50)}

Description:
{mod.get('description', 'No description available.')}
"""
        self.details_text.insert("1.0", info)
        self.details_text.config(state="disabled")

    def _install_mod(self):
        if not self.loader:
            messagebox.showerror("Error", "Please set the game folder first!")
            return
        filetypes = [("Mod files", "*.zip"), ("All files", "*.*")]
        path = filedialog.askopenfilename(title="Select Mod Archive", filetypes=filetypes)
        if not path: return
        try:
            name = self.loader.install_mod(path)
            self._refresh_mod_list()
            self.status_var.set(f"Installed mod: {name}")
            messagebox.showinfo("Success", f"Mod '{name}' installed!\n\nIt's disabled by default. Enable it in the list.")
        except Exception as e:
            messagebox.showerror("Install Failed", str(e))

    def _toggle_selected(self):
        if not self.selected_mod:
            messagebox.showinfo("Select Mod", "Please select a mod from the list first.")
            return
        try:
            new_status = self.loader.toggle_mod(self.selected_mod["name"], self.selected_mod["status"])
            self._refresh_mod_list()
            self.status_var.set(f"{self.selected_mod['name']} is now {new_status}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _delete_selected(self):
        if not self.selected_mod: return
        if not messagebox.askyesno("Confirm Delete", f"Permanently delete '{self.selected_mod['name']}'?\n\nThis cannot be undone!"):
            return
        try:
            self.loader.delete_mod(self.selected_mod["name"], self.selected_mod["status"])
            self._refresh_mod_list()
            self.details_text.config(state="normal")
            self.details_text.delete("1.0", "end")
            self.details_text.config(state="disabled")
            self.status_var.set(f"Deleted: {self.selected_mod['name']}")
            self.selected_mod = None
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _apply_mods(self):
        if not self.loader:
            messagebox.showerror("Error", "No game folder loaded!")
            return
        try:
            applied = self.loader.apply_mods()
            msg = "Applied mods:\n" + "\n".join(f" • {m}" for m in applied) if applied else "No active mods to apply."
            self.status_var.set(f"Applied {len(applied)} mod(s)")
            messagebox.showinfo("Mods Applied", msg)
        except Exception as e:
            messagebox.showerror("Apply Failed", str(e))

    def _restore(self):
        if not self.loader: return
        if messagebox.askyesno("Confirm Restore", "Restore all original game files?\n\nThis will remove all mod changes."):
            try:
                self.loader.restore_originals()
                self.status_var.set("Original files restored")
                messagebox.showinfo("Restored", "All original game files have been restored.")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _launch(self):
        if not self.loader:
            messagebox.showerror("Error", "Set the game folder first!")
            return
        result = self.loader.launch_game()
        if result == "desktop":
            self.status_var.set("Launched desktop version")
        elif result == "web":
            self.status_var.set("Launched web version in browser")
        else:
            messagebox.showerror("Launch Failed", "Could not find game executable or HTML file.")

def main():
    root = tk.Tk()
    try:
        root.iconbitmap("sheep.ico")
    except:
        pass
    app = ModLoaderUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
