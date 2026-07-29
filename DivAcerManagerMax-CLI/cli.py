import os
import sys
import threading
import time
import readchar
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich import box

from api import DAMXClient

console = Console()

MIN_WIDTH = 80
MIN_HEIGHT = 22

def get_system_telemetry() -> dict:
    metrics = {
        "cpu_temp": "N/A",
        "gpu_temp": "N/A",
        "cpu_rpm": "N/A",
        "gpu_rpm": "N/A",
    }
    
    hwmon_base = "/sys/class/hwmon"
    if os.path.exists(hwmon_base):
        try:
            for hwmon in os.listdir(hwmon_base):
                path = os.path.join(hwmon_base, hwmon)
                name_file = os.path.join(path, "name")
                if os.path.exists(name_file):
                    with open(name_file, "r") as f:
                        name = f.read().strip()
                    
                    if any(k in name for k in ("coretemp", "k10temp", "zenpower")):
                        temp_file = os.path.join(path, "temp1_input")
                        if os.path.exists(temp_file):
                            with open(temp_file, "r") as tf:
                                metrics["cpu_temp"] = f"{int(tf.read().strip()) / 1000:.1f}°C"
                    
                    if any(k in name for k in ("acer", "predator", "nitro")):
                        for i in (1, 2):
                            fan_file = os.path.join(path, f"fan{i}_input")
                            if os.path.exists(fan_file):
                                with open(fan_file, "r") as ff:
                                    val = ff.read().strip()
                                    if i == 1:
                                        metrics["cpu_rpm"] = f"{val} RPM"
                                    else:
                                        metrics["gpu_rpm"] = f"{val} RPM"
        except Exception:
            pass

    if metrics["gpu_temp"] == "N/A":
        try:
            import subprocess
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
            if res.returncode == 0 and res.stdout.strip():
                metrics["gpu_temp"] = f"{res.stdout.strip()}°C"
        except Exception:
            pass

    return metrics


class DAMXApp:
    def __init__(self, client: DAMXClient):
        self.client = client
        self.current_view = "MAIN"
        self.status_msg = ""
        self.running = True
        
        # Color definitions: (Name, R, G, B, Hex)
        self.rgb_presets = {
            "1": ("Red", 255, 0, 0, "FF0000"),
            "2": ("Green", 0, 255, 0, "00FF00"),
            "3": ("Blue", 0, 0, 255, "0000FF"),
            "4": ("Cyan", 0, 255, 255, "00FFFF"),
            "5": ("Magenta", 255, 0, 255, "FF00FF"),
            "6": ("Yellow", 255, 255, 0, "FFFF00"),
            "7": ("White", 255, 255, 255, "FFFFFF"),
            "0": ("Off", 0, 0, 0, "000000"),
        }

    def render(self) -> Layout:
        term_size = os.get_terminal_size()
        if term_size.columns < MIN_WIDTH or term_size.lines < MIN_HEIGHT:
            layout = Layout()
            msg = (
                f"[bold red]Terminal Window Too Small![/bold red]\n\n"
                f"Current Size: [yellow]{term_size.columns}x{term_size.lines}[/yellow]\n"
                f"Required Size: [green]{MIN_WIDTH}x{MIN_HEIGHT}[/green]\n\n"
                f"[dim]Please enlarge or resize your terminal to continue...[/dim]"
            )
            layout.update(Panel(msg, box=box.ROUNDED, border_style="red"))
            return layout

        try:
            settings = self.client.get_all_settings()
        except Exception:
            settings = {}

        if self.current_view == "MAIN":
            return self._render_main_dashboard(settings)
        elif self.current_view == "THERMAL":
            return self._render_thermal_menu(settings)
        elif self.current_view == "FAN":
            return self._render_fan_menu(settings)
        elif self.current_view == "RGB":
            return self._render_rgb_menu()

        return Layout()

    def _render_main_dashboard(self, settings: dict) -> Layout:
        telemetry = get_system_telemetry()
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=4),
            Layout(name="sys_info", size=5),
            Layout(name="telemetry", size=7),
            Layout(name="menu")
        )

        layout["header"].update(
            Panel(
                "[bold cyan]DAMX Daemon Control Center[/bold cyan]\n"
                "[dim]Hardware Control & Lighting Interface[/dim]",
                box=box.DOUBLE, border_style="cyan"
            )
        )

        sys_table = Table(box=box.ROUNDED, expand=True)
        sys_table.add_column("Laptop Model", style="bold yellow")
        sys_table.add_column("Daemon Version", style="green")
        sys_table.add_column("Driver Version", style="green")
        sys_table.add_row(
            settings.get("laptop_type", "Unknown"),
            settings.get("version", "N/A"),
            settings.get("driver_version", "N/A")
        )
        layout["sys_info"].update(sys_table)

        controls_table = Table(title="Live Telemetry & Controls", box=box.ROUNDED, expand=True)
        controls_table.add_column("Component", style="bold yellow")
        controls_table.add_column("Metrics / State", style="cyan")

        thermal = settings.get("thermal_profile", {})
        controls_table.add_row("Thermal Profile", thermal.get("current", "N/A").upper())
        controls_table.add_row("CPU Telemetry", f"Temp: [bold red]{telemetry['cpu_temp']}[/bold red] | Speed: [bold green]{telemetry['cpu_rpm']}[/bold green]")
        controls_table.add_row("GPU Telemetry", f"Temp: [bold red]{telemetry['gpu_temp']}[/bold red] | Speed: [bold green]{telemetry['gpu_rpm']}[/bold green]")

        fans = settings.get("fan_speed", {})
        cpu_fan, gpu_fan = fans.get("cpu", "0"), fans.get("gpu", "0")
        cpu_mode = "AUTO" if str(cpu_fan) == "0" else f"{cpu_fan}%"
        gpu_mode = "AUTO" if str(gpu_fan) == "0" else f"{gpu_fan}%"
        controls_table.add_row("Fan Speed Target", f"CPU Target: {cpu_mode} | GPU Target: {gpu_mode}")

        layout["telemetry"].update(controls_table)

        menu_text = (
            "[bold cyan]Actions (Press key):[/bold cyan]\n"
            "  [[yellow]1[/yellow]] Thermal Profiles\n"
            "  [[yellow]2[/yellow]] Fan Speed Controls\n"
            "  [[yellow]3[/yellow]] Keyboard Static RGB\n"
            "  [[yellow]q[/yellow]] Exit\n"
        )
        if self.status_msg:
            menu_text += f"\n{self.status_msg}"

        layout["menu"].update(Panel(menu_text, box=box.SIMPLE))
        return layout

    def _render_thermal_menu(self, settings: dict) -> Layout:
        layout = Layout()
        thermal = settings.get("thermal_profile", {})
        available = thermal.get("available", [])
        current = thermal.get("current", "")

        content = f"[bold]Current Profile:[/bold] [cyan]{current}[/cyan]\n\n"
        self.thermal_map = {}

        for idx, profile in enumerate(available, 1):
            key = str(idx)
            active = " [bold green](Active)[/bold green]" if profile == current else ""
            content += f"  [[yellow]{key}[/yellow]] {profile}{active}\n"
            self.thermal_map[key] = profile

        content += "\n  [[yellow]b[/yellow]] Back\n  [[yellow]q[/yellow]] Exit"
        if self.status_msg:
            content += f"\n\n{self.status_msg}"

        layout.update(Panel(content, title="Thermal Profiles", border_style="cyan"))
        return layout

    def _render_fan_menu(self, settings: dict) -> Layout:
        layout = Layout()
        fans = settings.get("fan_speed", {})
        cpu_val, gpu_val = fans.get('cpu', '0'), fans.get('gpu', '0')
        cpu_str = "AUTO" if str(cpu_val) == "0" else f"{cpu_val}%"
        gpu_str = "AUTO" if str(gpu_val) == "0" else f"{gpu_str}%"

        content = (
            f"[bold]Current Fan Mode:[/bold] CPU: [cyan]{cpu_str}[/cyan] | GPU: [cyan]{gpu_str}[/cyan]\n\n"
            "  [[yellow]a[/yellow]] AUTO Fan Mode\n"
            "  [[yellow]m[/yellow]] MAX Speed (100%)\n"
            "  [[yellow]7[/yellow]] 75% Speed\n"
            "  [[yellow]5[/yellow]] 50% Speed\n\n"
            "  [[yellow]b[/yellow]] Back\n"
            "  [[yellow]q[/yellow]] Exit"
        )
        if self.status_msg:
            content += f"\n\n{self.status_msg}"

        layout.update(Panel(content, title="Fan Control", border_style="cyan"))
        return layout

    def _render_rgb_menu(self) -> Layout:
        layout = Layout()
        content = "[bold]Static RGB Presets:[/bold]\n\n"

        for key, (name, _, _, _, _) in self.rgb_presets.items():
            content += f"  [[yellow]{key}[/yellow]] Solid {name}\n"

        content += "\n  [[yellow]b[/yellow]] Back\n  [[yellow]q[/yellow]] Exit"
        if self.status_msg:
            content += f"\n\n{self.status_msg}"

        layout.update(Panel(content, title="Static RGB Control", border_style="cyan"))
        return layout

    def handle_input(self, key: str):
        if key == "q":
            self.running = False
            return

        if self.current_view == "MAIN":
            if key == "1":
                self.current_view = "THERMAL"
                self.status_msg = ""
            elif key == "2":
                self.current_view = "FAN"
                self.status_msg = ""
            elif key == "3":
                self.current_view = "RGB"
                self.status_msg = ""

        elif self.current_view == "THERMAL":
            if key == "b":
                self.current_view = "MAIN"
                self.status_msg = ""
            elif hasattr(self, "thermal_map") and key in self.thermal_map:
                profile = self.thermal_map[key]
                if self.client.set_thermal_profile(profile):
                    self.status_msg = f"[bold green]✓[/bold green] Profile set to [cyan]{profile}[/cyan]"
                else:
                    self.status_msg = "[bold red]✗[/bold red] Failed to set profile."

        elif self.current_view == "FAN":
            if key == "b":
                self.current_view = "MAIN"
                self.status_msg = ""
            elif key == "a":
                if self.client.set_fan_speed(0, 0):
                    self.status_msg = "[bold green]✓[/bold green] Fans set to [cyan]AUTO[/cyan]"
            elif key == "m":
                if self.client.set_fan_speed(100, 100):
                    self.status_msg = "[bold green]✓[/bold green] Fans set to [cyan]MAX (100%)[/cyan]"
            elif key == "7":
                if self.client.set_fan_speed(75, 75):
                    self.status_msg = "[bold green]✓[/bold green] Fans set to [cyan]75%[/cyan]"
            elif key == "5":
                if self.client.set_fan_speed(50, 50):
                    self.status_msg = "[bold green]✓[/bold green] Fans set to [cyan]50%[/cyan]"

        elif self.current_view == "RGB":
            if key == "b":
                self.current_view = "MAIN"
                self.status_msg = ""
            elif key in self.rgb_presets:
                name, r, g, b, hex_val = self.rgb_presets[key]
                
                # Payload format for 4-Zone mode (r,g,b for 4 zones + brightness 100)
                four_zone_payload = f"{r},{g},{b},{r},{g},{b},{r},{g},{b},{r},{g},{b},100"
                per_zone_payload = f"{hex_val},{hex_val},{hex_val},{hex_val},100"

                success = False
                try:
                    res = self.client.send_command("set_four_zone_mode", {"mode": four_zone_payload})
                    if res.get("success"):
                        success = True
                except Exception:
                    pass

                if not success:
                    try:
                        res = self.client.send_command("set_per_zone_mode", {"mode": per_zone_payload})
                        if res.get("success"):
                            success = True
                    except Exception:
                        pass

                if success:
                    self.status_msg = f"[bold green]✓[/bold green] RGB set to [cyan]{name}[/cyan]"
                else:
                    self.status_msg = "[bold red]✗[/bold red] Failed to update RGB."


def main():
    try:
        with DAMXClient() as client:
            if not client.is_connected:
                console.print("[bold red]Error:[/bold red] Could not connect to DAMX daemon at [yellow]/var/run/DAMX.sock[/yellow]")
                sys.exit(1)

            app = DAMXApp(client)

            def listen_keys():
                while app.running:
                    try:
                        k = readchar.readkey().lower()
                        if k in ('\x03', '\x04'):
                            app.running = False
                            break
                        app.handle_input(k)
                    except Exception:
                        pass

            input_thread = threading.Thread(target=listen_keys, daemon=True)
            input_thread.start()

            with Live(app.render(), console=console, refresh_per_second=10, screen=False) as live:
                while app.running:
                    live.update(app.render())
                    time.sleep(0.1)

    except KeyboardInterrupt:
        sys.exit(0)

if __name__ == "__main__":
    main()