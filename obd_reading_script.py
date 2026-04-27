from __future__ import annotations

import time
from pathlib import Path

import obd


PORT = "/dev/cu.usbserial-A77IPOSO"
OUTPUT_FILE = Path("obd_readings_dump.txt")


def safe_query(connection: obd.OBD, command) -> str:
    try:
        response = connection.query(command, force=True)
        if response is None or response.is_null():
            return "NO DATA"
        return str(response.value)
    except Exception as exc:
        return f"ERROR: {exc}"


def main() -> None:
    print(f"Connecting to {PORT}...")
    connection = obd.OBD(PORT, fast=True)
    connected = connection is not None and connection.is_connected()
    print("Connected:", connected)

    lines: list[str] = []
    lines.append(f"Port: {PORT}")
    lines.append(f"Connected: {connected}")
    lines.append(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    if not connected:
        lines.append("Failed to connect to OBD adapter/car.")
        OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
        print(f"Saved to {OUTPUT_FILE.resolve()}")
        return

    supported = sorted(connection.supported_commands, key=lambda c: str(c))
    lines.append(f"Supported command count: {len(supported)}")
    lines.append("")
    lines.append("READINGS:")
    lines.append("-" * 80)

    for cmd in supported:
        name = str(cmd)
        value = safe_query(connection, cmd)
        lines.append(f"{name:<40} -> {value}")

    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved to {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()