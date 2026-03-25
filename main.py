import os
import subprocess
import csv
import time
import re
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.align import Align
from rich.live import Live

console = Console()

# --- DYNAMIC CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "hdd_inventory_log.csv")
CERT_DIR = os.path.join(BASE_DIR, "certificates")
OS_DRIVE = "sda"  # CRITICAL: Verify this is your OS drive via 'lsblk'

os.makedirs(CERT_DIR, exist_ok=True)

def initialize_system():
    """Checks for CSV existence and announces status to user."""
    headers = ["Date", "Serial", "Model", "Capacity", "Hours", "Bad_Sectors", "SMART_Status", "Grade", "Wipe_Result", "Certificate_File"]
    
    # Corrected Centered Panel for initialize_system
    audit_panel = Panel(
        Align.center("[bold yellow]SYSTEM AUDIT IN PROGRESS...[/bold yellow]"),
        border_style="yellow"
    )
    console.print(audit_panel)
    
    if os.path.isfile(CSV_FILE):
        console.print(f"[bold green]✔ FOUND:[/bold green] Inventory log at {CSV_FILE}")
    else:
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
        console.print(f"[bold cyan]★ CREATED:[/bold cyan] New inventory log initialized.")
    
    if os.path.isdir(CERT_DIR):
        console.print(f"[bold green]✔ FOUND:[/bold green] Certificate directory active.")
    
    time.sleep(1.5)

def get_drive_list():
    cmd = ["lsblk", "-dno", "NAME,SIZE,MODEL,SERIAL"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    drives = []
    for line in result.stdout.strip().split('\n'):
        parts = line.split()
        if parts and parts[0].startswith("sd") and parts[0] != OS_DRIVE:
            drives.append({
                "name": parts[0], "size": parts[1],
                "model": " ".join(parts[2:-1]),
                "serial": parts[-1] if len(parts) > 3 else "UNKNOWN"
            })
    return drives

def generate_inventory_table():
    drives = get_drive_list()
    table = Table(title="[bold blue]Ready to Process[/bold blue]", border_style="blue")
    table.add_column("Device", style="yellow")
    table.add_column("Model")
    table.add_column("Size")
    table.add_column("Serial", style="green")
    for d in drives: table.add_row(d['name'], d['model'], d['size'], d['serial'])
    return table

def get_detailed_smart(drive_name):
    dev_path = f"/dev/{drive_name}"
    subprocess.run(["sudo", "smartctl", "-t", "short", dev_path], capture_output=True)
    attr_raw = subprocess.run(["sudo", "smartctl", "-A", dev_path], capture_output=True, text=True).stdout
    hours, bad_sectors = 0, 0
    h_match = re.search(r"Power_On_Hours\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)", attr_raw)
    if h_match: hours = int(h_match.group(1))
    b_match = re.search(r"Reallocated_Sector_Ct\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)", attr_raw)
    if b_match: bad_sectors = int(b_match.group(1))
    health_raw = subprocess.run(["sudo", "smartctl", "-H", dev_path], capture_output=True, text=True).stdout
    status = "PASSED" if "test result: PASSED" in health_raw else "FAILED"
    return status, hours, bad_sectors

def log_data(result_data):
    headers = ["Date", "Serial", "Model", "Capacity", "Hours", "Bad_Sectors", "SMART_Status", "Grade", "Wipe_Result", "Certificate_File"]
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow(result_data)
    
    if "SUCCESS" in result_data['Wipe_Result']:
        cert_name = result_data['Certificate_File']
        cert_path = os.path.join(CERT_DIR, cert_name)
        with open(cert_path, 'w') as f:
            f.write(f"--- DATA ERASURE & INTEGRITY CERTIFICATE ---\n")
            f.write(f"Serial: {result_data['Serial']}\nModel: {result_data['Model']}\n")
            f.write(f"Grade: {result_data['Grade']}\nDate: {result_data['Date']}\n")
            f.write(f"Hours: {result_data['Hours']}\nBad Sectors: {result_data['Bad_Sectors']}\n")
            f.write(f"Wipe Result: {result_data['Wipe_Result']}\n")
            f.write(f"--- END OF REPORT ---")

def process_drive(drive_info, mode):
    drive_name = drive_info['name']
    serial = drive_info['serial']
    dev_path = f"/dev/{drive_name}"

    if serial == "UNKNOWN" or serial == "":
        console.print("[bold yellow]Identity Required:[/bold yellow] Device did not provide a Serial Number.")
        serial = Prompt.ask("Please enter a Custom ID or Serial for this drive")

    subprocess.run(["sudo", "umount", "-l", f"{dev_path}*"], capture_output=True)
    
    with console.status("[bold yellow]Running SMART Diagnostics...") as status_msg:
        status, hours, pre_bad = get_detailed_smart(drive_name)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    wipe_result = "N/A (Verify Only)"
    
    if mode == "1":
        size_bytes = int(subprocess.check_output(["blockdev", "--getsize64", dev_path]))
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), "[progress.percentage]{task.percentage:>3.0f}%", DownloadColumn(), TransferSpeedColumn(), "ETA:", TimeRemainingColumn(), console=console) as progress:
            task = progress.add_task(f"[cyan]Wiping {serial}", total=size_bytes)
            proc = subprocess.Popen(['sudo', 'dd', 'if=/dev/zero', f'of={dev_path}', 'bs=1M', 'status=none', 'conv=fdatasync'], stderr=subprocess.PIPE)
            while proc.poll() is None:
                if os.path.exists(f"/sys/block/{drive_name}/stat"):
                    with open(f"/sys/block/{drive_name}/stat", 'r') as f:
                        sectors_written = int(f.read().split()[6])
                        progress.update(task, completed=sectors_written * 512)
                time.sleep(1)
        wipe_result = "SUCCESS" if proc.returncode == 0 else "ERROR"
        console.print("[bold magenta]Cooling & Verifying Integrity Check...[/bold magenta]")
        time.sleep(5)
    
    final_status, final_hours, post_bad = get_detailed_smart(drive_name)
    grade = "Grade A" if post_bad == 0 and final_hours < 20000 else "Grade B" if post_bad == 0 and final_hours < 50000 else "Grade C"
    if post_bad > pre_bad: grade = "Grade C (Deteriorated)"

    res = {
        "Date": timestamp, "Serial": serial, "Model": drive_info['model'], "Capacity": drive_info['size'],
        "Hours": final_hours, "Bad_Sectors": post_bad, "SMART_Status": final_status,
        "Grade": grade, "Wipe_Result": wipe_result, "Certificate_File": f"CERT_{serial}.txt"
    }
    
    log_data(res)

    console.clear()
    results_table = Table(title="[bold green]FINAL DRIVE REPORT[/bold green]", show_header=False, border_style="green")
    for key, value in res.items():
        results_table.add_row(f"[bold white]{key}[/bold white]", str(value))
    
    console.print(Panel(results_table, expand=False))
    console.print("\n[bold green]✔ LOGGED SUCCESSFULLY.[/bold green]")
    
    if Confirm.ask("\n[bold yellow]Spin down drive for safe removal?[/bold yellow]"):
        subprocess.run(["sudo", "hdparm", "-Y", dev_path], capture_output=True)
        console.print(f"[bold green]Drive {drive_name} is now parked. You can unplug it.[/bold green]")
        input("\nPress Enter to return to main menu...")

def main():
    console.clear()
    initialize_system()
    while True:
        console.clear()
        console.print(Panel(Align.center("[bold cyan]HDD COMMAND CENTER v5.2[/bold cyan]\n[white]Select Mode: (1) Prep for Sale | (2) Verify Only[/white]"), border_style="cyan"))
        
        with Live(generate_inventory_table(), refresh_per_second=1):
            try:
                choice = Prompt.ask("\nType [bold yellow]Device Name[/bold yellow] (sdb) or [bold red]'q'[/bold red]")
                if choice.lower() == 'q': exit()
            except KeyboardInterrupt: exit()

        drives = get_drive_list()
        selected = next((d for d in drives if d['name'] == choice), None)
        
        if selected:
            mode = Prompt.ask(f"\n[bold white]Action for {selected['name']}[/bold white]", choices=["1", "2"], default="1")
            if Confirm.ask(f"Confirm execution for {selected['serial']}?"):
                process_drive(selected, mode)
        else:
            console.print("[red]Invalid device.[/red]")
            time.sleep(1)

if __name__ == "__main__":
    main()
