import os
import shutil
import psutil


def get_system_metrics() -> dict:
    """Retrieve system CPU, RAM, and Disk metrics."""
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    ws_dir = os.getenv("WORKSPACE_DIR", "/workspace")
    disk_target = ws_dir if os.path.exists(ws_dir) else "/"
    disk = shutil.disk_usage(disk_target)
    
    return {
        "cpu_percent": round(cpu_percent, 1),
        "memory_total": mem.total,
        "memory_used": mem.used,
        "memory_available": mem.available,
        "memory_percent": round(mem.percent, 1),
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_free": disk.free,
        "disk_percent": round((disk.used / disk.total) * 100, 1) if disk.total > 0 else 0.0,
    }

