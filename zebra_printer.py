"""Sending ZPL straight to a Zebra label printer

Two ways to reach the printer:
  - A printer installed in Windows (USB, or a network printer someone already added).
    The ZPL goes through the Windows print queue as a RAW job, so the Zebra driver
    passes it to the printer untouched.
  - A network printer by IP address, straight to its raw port 9100. No driver needed.
"""

import re
import socket
import sys

RAW_PORT = 9100
NETWORK_TIMEOUT_S = 10
CHUNK_BYTES = 64 * 1024

_ZEBRA_WORDS = ("zebra", "zdesigner", "zpl")
# "ZDesigner ZM400 200 dpi (ZPL)", "ZDesigner ZD421-203dpi ZPL", "... 300 dpi ..."
_DPI_IN_NAME = re.compile(r"(200|203|300|600)\s*dpi", re.IGNORECASE)
_ADDRESS = re.compile(r"^([A-Za-z0-9.-]+)(?::(\d{1,5}))?$")


class PrinterError(Exception):
    """A plain message to show the user"""


def is_zebra(name):
    lowered = name.lower()
    return any(word in lowered for word in _ZEBRA_WORDS)


def dpi_from_name(name):
    """ZDesigner drivers are named like 'ZDesigner ZM400 200 dpi (ZPL)'. None if not in the name"""
    match = _DPI_IN_NAME.search(name)
    if not match:
        return None
    dpi = int(match.group(1))
    return 203 if dpi == 200 else dpi  # Zebra rounds 203 dpi down to "200" in names


def list_printers():
    """Names of the printers installed in Windows, Zebra ones first"""
    if sys.platform != "win32":
        return []
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    names = {info["pPrinterName"] for info in win32print.EnumPrinters(flags, None, 4)}
    return sorted(names, key=lambda name: (not is_zebra(name), name.lower()))


def send_to_windows_printer(printer_name, data, job_name="Labels"):
    """Hand raw ZPL bytes to a Windows print queue"""
    import pywintypes
    import win32print

    try:
        handle = win32print.OpenPrinter(printer_name)
    except pywintypes.error as error:
        raise PrinterError(
            'The printer "%s" could not be found. It may have been removed or '
            "renamed in Windows.\n\nDetails: %s" % (printer_name, error.strerror)
        ) from error
    try:
        win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            for start in range(0, len(data), CHUNK_BYTES):
                win32print.WritePrinter(handle, data[start:start + CHUNK_BYTES])
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    except pywintypes.error as error:
        raise PrinterError(
            'Windows could not send the labels to "%s".\n\nDetails: %s'
            % (printer_name, error.strerror)
        ) from error
    finally:
        win32print.ClosePrinter(handle)


def parse_address(text):
    """'192.168.1.50' or '192.168.1.50:9100' -> (host, port). Raises ValueError"""
    match = _ADDRESS.match(text.strip())
    if not match:
        raise ValueError("Type the printer's IP address, like 192.168.1.50")
    port = int(match.group(2) or RAW_PORT)
    if not 0 < port < 65536:
        raise ValueError("The port number after ':' must be between 1 and 65535.")
    return match.group(1), port


def send_to_network_printer(address, data):
    """Send raw ZPL bytes to a printer's raw port"""
    host, port = parse_address(address)
    try:
        with socket.create_connection((host, port), timeout=NETWORK_TIMEOUT_S) as conn:
            conn.sendall(data)
    except OSError as error:
        raise PrinterError(
            "The printer at %s did not answer. Check that it is on, connected to the "
            "network, and that the address is right.\n\nDetails: %s"
            % (address, error.strerror or error)
        ) from error
