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

def get_os_drive():
    try:
        cmd = "lsblk -no NAME,MOUNTPOINT | grep ' /$' | awk '{print $1}'"
        os_partition = subprocess.check_output(cmd, shell=True, text=True).strip()
        return re.sub(r'\d+$', '', os_partition)
    except:
        return "sda" 

OS_DRIVE = get_os_drive()
os.makedirs(CERT_DIR, exist_ok=True)

def initialize_system():
    # ADDED: Failure_Reason to headers
    headers = ["Date", "Serial", "Model", "Capacity", "Hours", "Bad_Sectors", "SMART_Status", "Failure_Reason", "Grade", "Wipe_Result", "Certificate_File"]
    console.print(Panel(Align.center("[bold yellow]SYSTEM AUDIT IN PROGRESS...[/bold yellow]"), border_style="yellow"))
    if not os.path.isfile(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
        console.print(f"[bold cyan]★ CREATED:[/bold cyan] New inventory log with Failure Tracking.")
    else:
        console.print(f"[bold green]✔ READY:[/bold green] Logging to {CSV_FILE}")
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
    table = Table(title="[bold blue]Detected Drives (Excluding OS)[/bold blue]", border_style="blue")
    table.add_column("Device", style="yellow")
    table.add_column("Model")
    table.add_column("Size")
    table.add_column("Serial", style="green")
    for d in drives: table.add_row(d['name'], d['model'], d['size'], d['serial'])
    return table

def get_detailed_smart(drive_name):
    dev_path = f"/dev/{drive_name}"
    attr_raw = subprocess.run(["sudo", "smartctl", "-d", "sat", "-A", dev_path], capture_output=True, text=True).stdout
    
    hours, bad_sectors = 0, 0
    failing_attributes = []
    
    for line in attr_raw.splitlines():
        parts = line.split()
        if len(parts) >= 10:
            # Check for standard Hours and Bad Sectors
            if parts[0] == "9" or "Power_On_Hours" in parts[1]:
                try: hours = int(parts[-1])
                except: pass
            if parts[0] == "5" or "Reallocated_Sector_Ct" in parts[1]:
                try: bad_sectors = int(parts[-1])
                except: pass
            
            # THE SMART PARSER: Check if this specific attribute is failing right now
            if "FAILING_NOW" in line:
                failing_attributes.append(parts[1]) # Grabs the name of the broken component

    health_raw = subprocess.run(["sudo", "smartctl", "-d", "sat", "-H", dev_path], capture_output=True, text=True).stdout
    status = "PASSED" if "test result: PASSED" in health_raw else "FAILED"
    
    # Formulate the Failure Reason
    failure_reason = "N/A"
    if status == "FAILED":
        if failing_attributes:
            failure_reason = f"CRITICAL: {', '.join(failing_attributes)}"
        else:
            # Sometimes a drive fails the health check but hides the specific attribute
            failure_reason = "General Firmware/Hardware Fault"
            
    # Also flag high bad sectors even if the drive claims it "PASSED"
    if bad_sectors > 0 and status == "PASSED":
        failure_reason = f"WARNING: {bad_sectors} Bad Sectors Detected"

    return status, hours, bad_sectors, failure_reason

def log_data(result_data):
    headers = ["Date", "Serial", "Model", "Capacity", "Hours", "Bad_Sectors", "SMART_Status", "Failure_Reason", "Grade", "Wipe_Result", "Certificate_File"]
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow(result_data)
    
    cert_path = os.path.join(CERT_DIR, result_data['Certificate_File'])
    with open(cert_path, 'w') as f:
        f.write(f"--- HDD PREP REPORT ---\n")
        f.write(f"Serial: {result_data['Serial']}\n")
        f.write(f"Grade:  {result_data['Grade']}\n")
        f.write(f"Hours:  {result_data['Hours']}\n")
        f.write(f"Health: {result_data['SMART_Status']}\n")
        f.write(f"Reason: {result_data['Failure_Reason']}\n")
        f.write(f"---")

def process_drive(drive_info, mode):
    drive_name = drive_info['name']
    serial = drive_info['serial']
    if serial == "UNKNOWN": serial = Prompt.ask("[bold yellow]Enter Serial[/bold yellow]")

    subprocess.run(["sudo", "umount", "-l", f"/dev/{drive_name}*"], capture_output=True)
    
    with console.status("[bold yellow]Scanning Health...") as status_msg:
        status, hours, pre_bad, pre_reason = get_detailed_smart(drive_name)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    wipe_res = "N/A (Verify Only)"
    if mode == "1":
        size_bytes = int(subprocess.check_output(["blockdev", "--getsize64", f"/dev/{drive_name}"]))
        with Progress(SpinnerColumn(), BarColumn(), "[progress.percentage]{task.percentage:>3.0f}%", DownloadColumn(), TransferSpeedColumn(), "ETA:", TimeRemainingColumn(), console=console) as progress:
            task = progress.add_task(f"[cyan]Wiping {serial}", total=size_bytes)
            proc = subprocess.Popen(['sudo', 'dd', 'if=/dev/zero', f'of=/dev/{drive_name}', 'bs=1M', 'status=none', 'conv=fdatasync'], stderr=subprocess.PIPE)
            while proc.poll() is None:
                if os.path.exists(f"/sys/block/{drive_name}/stat"):
                    with open(f"/sys/block/{drive_name}/stat", 'r') as f:
                        sectors_written = int(f.read().split()[6])
                        progress.update(task, completed=sectors_written * 512)
                time.sleep(1)
        wipe_res = "SUCCESS" if proc.returncode == 0 else "ERROR"

    f_status, f_hours, post_bad, f_reason = get_detailed_smart(drive_name)
    
    # Adjust Grade based on FAILED status
    if f_status == "FAILED" or post_bad > 0:
        grade = "Grade C/F (FAILED)"
    elif f_hours < 20000:
        grade = "Grade A"
    elif f_hours < 50000:
        grade = "Grade B"
    else:
        grade = "Grade C"

    res = {
        "Date": timestamp, "Serial": serial, "Model": drive_info['model'], "Capacity": drive_info['size'],
        "Hours": f_hours, "Bad_Sectors": post_bad, "SMART_Status": f_status, "Failure_Reason": f_reason,
        "Grade": grade, "Wipe_Result": wipe_res, "Certificate_File": f"CERT_{serial}.txt"
    }
    log_data(res)

    console.clear()
    table = Table(title="[bold green]FINAL DRIVE REPORT[/bold green]", show_header=False)
    for k, v in res.items(): 
        # Highlight failures in red on the terminal screen
        if k == "Failure_Reason" and v != "N/A":
            table.add_row(f"[bold red]{k}[/bold red]", f"[bold red]{str(v)}[/bold red]")
        else:
            table.add_row(k, str(v))
            
    console.print(Panel(table, expand=False))
    
    if Confirm.ask("\n[bold yellow]Spin down for safe removal?[/bold yellow]"):
        subprocess.run(["sudo", "hdparm", "-Y", f"/dev/{drive_name}"], capture_output=True)
        input("\n[bold green]Ready to unplug.[/bold green] Press Enter to continue...")

def main():
    initialize_system()
    while True:
        console.clear()
        console.print(Panel(Align.center("[bold cyan]HDD COMMAND CENTER v5.7[/bold cyan]"), border_style="cyan"))
        with Live(generate_inventory_table(), refresh_per_second=1):
            choice = Prompt.ask("\nDevice (e.g. sdb) or 'q'")
            if choice.lower() == 'q': break
        
        drives = get_drive_list()
        sel = next((d for d in drives if d['name'] == choice), None)
        if sel:
            mode = Prompt.ask("\n[1] Full Prep | [2] Verify Only", choices=["1", "2"], default="1")
            if Confirm.ask(f"Start {sel['name']}?"):
                process_drive(sel, mode)

if __name__ == "__main__":
    main()
