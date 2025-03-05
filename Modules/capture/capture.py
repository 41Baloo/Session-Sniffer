# Standard Python Libraries
import subprocess
from pathlib import Path
from typing import Callable, Optional
from datetime import datetime


class TSharkCrashException(Exception):
    pass

class Frame:
    def __init__(self, time_epoch: str):
        self.datetime = converts_tshark_packet_timestamp_to_datetime_object(time_epoch)

class IP:
    def __init__(self, src: str, dst: str):
        self.src = src
        self.dst = dst

class UDP:
    def __init__(self, srcport: str, dstport: str):
        self.srcport = int(srcport) if srcport else None
        self.dstport = int(dstport) if dstport else None

class Packet:
    def __init__(self, fields: list[str]):
        self.frame = Frame(fields[0])
        self.ip = IP(fields[1], fields[2])
        self.udp = UDP(fields[3], fields[4])

class PacketCapture:
    def __init__(
        self,
        interface: str,
        tshark_path: Path,
        tshark_version: str,
        capture_filter: Optional[str] = None,
        display_filter: Optional[str] = None
    ):
        from Modules.constants.standard import WIRESHARK_VERSION_PATTERN

        self.interface = interface
        self.tshark_path = tshark_path
        self.tshark_version = tshark_version
        self.capture_filter = capture_filter
        self.display_filter = display_filter

        # Extract Wireshark version
        if not (match := WIRESHARK_VERSION_PATTERN.search(tshark_version)):
            raise ValueError("Could not extract Wireshark version")

        extracted_version = match.group("version")
        if not isinstance(extracted_version, str):
            raise TypeError(f'Expected "str", got "{type(extracted_version).__name__}"')

        self.extracted_tshark_version = extracted_version

        # Build TShark command
        self._tshark_command = [
            str(tshark_path),
            '-l', '-n', '-Q',
            '--log-level', 'critical',
            '-B', '1',
            '-i', interface,
            *(['-f', capture_filter] if capture_filter else []),
            *(['-Y', display_filter] if display_filter else []),
            '-T', 'fields',
            '-E', 'separator=|',
            '-e', 'frame.time_epoch',
            '-e', 'ip.src',
            '-e', 'ip.dst',
            '-e', 'udp.srcport',
            '-e', 'udp.dstport',
        ]
        self._tshark_process = None

    def live_capture(self, callback: Callable[[Packet], None], timeout: int | float):
        import time
        import queue
        import threading

        packets_queue = queue.Queue()

        def read_packets():
            for packet in self._capture_packets():
                packets_queue.put(packet)

        stdout_thread = threading.Thread(target=read_packets, daemon=True)
        stdout_thread.start()

        start_time = time.monotonic()

        while True:
            time_elapsed = time.monotonic() - start_time
            if time_elapsed >= timeout:
                if packets_queue.empty():
                    # NOTE: I don't use this code anyways, but returning `None` here seems like an issue to fix.
                    callback('None')
                else:
                    while not packets_queue.empty():
                        packet = packets_queue.get()
                        callback(packet)

                start_time = time.monotonic()

            time.sleep(0.1)

            # Ensure that the stdout_thread completes before exiting the method
            if not stdout_thread.is_alive():
                stdout_thread.join()
                break

    def apply_on_packets(self, callback: Callable[[Packet], None]):
        for packet in self._capture_packets():
            callback(packet)

    def _capture_packets(self):
        def process_tshark_stdout(line: str):
            return line.rstrip().split('|', 4)

        with subprocess.Popen(
            self._tshark_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        ) as process:
            self._tshark_process = process

            # Iterate over stdout line by line as it is being produced
            for line in process.stdout:
                yield Packet(process_tshark_stdout(line))

            # After stdout is done, check if there were any errors
            stderr_output = process.stderr.read()
            if process.returncode != 0:
                raise TSharkCrashException(f"TShark exited with error code {process.returncode}:\n{stderr_output.strip()}")

def converts_tshark_packet_timestamp_to_datetime_object(packet_frame_time_epoch: str):
    return datetime.fromtimestamp(timestamp=float(packet_frame_time_epoch))