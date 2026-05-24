import argparse
import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path

from src.features.acc_features import TYPE_ACC, parse_acc_packet

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    BleakClient = None
    BleakScanner = None


HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
POLAR_DEVICE_NAME = "Polar H10"
TYPE_ECG = 0x00
REALTIME_ECG_SAMPLE_RATE_HZ = 130
DEFAULT_ACC_SAMPLE_RATE_HZ = 50
DEFAULT_ACC_RANGE_G = 8
DEFAULT_COLLECTION_SECONDS = 330
WARMUP_ALLOWANCE_SECONDS = 30
MIN_USABLE_SECONDS = 300
SUPPORTED_ACC_SAMPLE_RATES_HZ = (25, 50, 100, 200)
SUPPORTED_ACC_RANGES_G = (2, 4, 8)

ECG_START_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
ECG_STOP_CMD = bytearray([0x03, 0x00])
ACC_STOP_CMD = bytearray([0x03, TYPE_ACC])

VALID_STATES = {"rest", "walk", "active"}


def _safe_name(value):
    value = str(value or "unknown").strip()
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value)


def _session_timestamp():
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def build_acc_start_cmd(sample_rate_hz=DEFAULT_ACC_SAMPLE_RATE_HZ, range_g=DEFAULT_ACC_RANGE_G):
    sample_rate_hz = int(sample_rate_hz)
    range_g = int(range_g)
    if sample_rate_hz not in SUPPORTED_ACC_SAMPLE_RATES_HZ:
        raise ValueError(f"ACC sample rate must be one of {SUPPORTED_ACC_SAMPLE_RATES_HZ}.")
    if range_g not in SUPPORTED_ACC_RANGES_G:
        raise ValueError(f"ACC range must be one of {SUPPORTED_ACC_RANGES_G}.")
    return bytearray(
        [
            0x02,
            TYPE_ACC,
            0x00,
            0x01,
            sample_rate_hz & 0xFF,
            (sample_rate_hz >> 8) & 0xFF,
            0x01,
            0x01,
            0x10,
            0x00,
            0x02,
            0x01,
            range_g & 0xFF,
            (range_g >> 8) & 0xFF,
        ]
    )


async def find_polar_h10(timeout=20):
    if BleakScanner is None:
        raise RuntimeError("bleak is not installed. Run: python -m pip install -r requirements.txt")

    def polar_filter(device, adv):
        if device.name and POLAR_DEVICE_NAME in device.name:
            return True
        if adv and getattr(adv, "local_name", None) and POLAR_DEVICE_NAME in adv.local_name:
            return True
        return False

    device = await BleakScanner.find_device_by_filter(polar_filter, timeout=timeout)
    if device is None:
        raise RuntimeError(f"Could not find {POLAR_DEVICE_NAME} during BLE scan.")
    return device.address


def parse_ecg_packet(data):
    if len(data) < 10 or (data[0] & 0x3F) != TYPE_ECG:
        return []

    samples = []
    for i in range(10, len(data) - 2, 3):
        raw = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
        if raw & 0x800000:
            raw -= 0x1000000
        samples.append(raw)
    return samples


def parse_rr_packet(data):
    if not data:
        return []

    flag = data[0]
    offset = 1
    offset += 2 if flag & 0x01 else 1
    if flag & 0x08:
        offset += 2

    intervals_ms = []
    if flag & 0x10:
        while offset + 1 < len(data):
            rr_raw = int.from_bytes(data[offset : offset + 2], "little")
            intervals_ms.append((rr_raw / 1024.0) * 1000.0)
            offset += 2
    return intervals_ms


async def collect_polar_session(
    address,
    duration_seconds,
    scan_timeout=20,
    acc_sample_rate_hz=DEFAULT_ACC_SAMPLE_RATE_HZ,
    acc_range_g=DEFAULT_ACC_RANGE_G,
):
    if BleakClient is None:
        raise RuntimeError("bleak is not installed. Run: python -m pip install -r requirements.txt")

    if not address:
        address = await find_polar_h10(timeout=scan_timeout)

    ecg_samples = []
    acc_samples = []
    rr_intervals_ms = []
    stats = {
        "pmd_packets_seen": 0,
        "pmd_ecg_packets_seen": 0,
        "pmd_acc_packets_seen": 0,
        "hr_packets_seen": 0,
        "acc_stream_started": False,
        "hr_stream_started": False,
    }

    def hr_callback(sender, data):
        stats["hr_packets_seen"] += 1
        rr_intervals_ms.extend(parse_rr_packet(bytes(data)))

    def pmd_callback(sender, data):
        payload = bytes(data)
        stats["pmd_packets_seen"] += 1
        if len(payload) < 10:
            return

        data_type = payload[0] & 0x3F
        if data_type == TYPE_ECG:
            samples = parse_ecg_packet(payload)
            if samples:
                stats["pmd_ecg_packets_seen"] += 1
                ecg_samples.extend(samples)
        elif data_type == TYPE_ACC:
            _, samples = parse_acc_packet(payload)
            if samples:
                stats["pmd_acc_packets_seen"] += 1
                acc_samples.extend(samples)

    print(f"Connecting to Polar H10 at {address}...")
    async with BleakClient(address, timeout=20) as client:
        if not client.is_connected:
            raise RuntimeError("Unable to connect to Polar H10.")

        try:
            await client.start_notify(HR_UUID, hr_callback)
            stats["hr_stream_started"] = True
            print("HR/RR stream enabled.")
        except Exception as exc:
            print(f"HR/RR stream unavailable, continuing with ECG/ACC: {exc}")

        await client.start_notify(PMD_DATA, pmd_callback)
        print("PMD data notifications enabled.")

        await client.write_gatt_char(PMD_CONTROL, ECG_START_CMD, response=True)
        await asyncio.sleep(0.3)
        print("ECG stream enabled.")

        try:
            await client.write_gatt_char(
                PMD_CONTROL,
                build_acc_start_cmd(
                    sample_rate_hz=acc_sample_rate_hz,
                    range_g=acc_range_g,
                ),
                response=True,
            )
            await asyncio.sleep(0.3)
            stats["acc_stream_started"] = True
            print(f"ACC stream enabled at {acc_sample_rate_hz}Hz, range {acc_range_g}G.")
        except Exception as exc:
            print(f"ACC stream unavailable, continuing ECG-only: {exc}")

        try:
            print(f"Collecting for {duration_seconds} seconds...")
            await asyncio.sleep(float(duration_seconds))
        finally:
            try:
                await client.write_gatt_char(PMD_CONTROL, ACC_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.write_gatt_char(PMD_CONTROL, ECG_STOP_CMD, response=True)
            except Exception:
                pass
            try:
                await client.stop_notify(PMD_DATA)
            except Exception:
                pass
            if stats["hr_stream_started"]:
                try:
                    await client.stop_notify(HR_UUID)
                except Exception:
                    pass

    return {
        "address": address,
        "ecg_samples": ecg_samples,
        "acc_samples": acc_samples,
        "rr_intervals_ms": rr_intervals_ms,
        "stats": stats,
    }


def write_ecg_csv(path, samples, sample_rate_hz):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "time_seconds", "ecg_uv"])
        for index, value in enumerate(samples):
            writer.writerow([index, index / float(sample_rate_hz), value])


def write_acc_csv(path, samples, sample_rate_hz):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "time_seconds", "x_mg", "y_mg", "z_mg", "vm_mg"])
        for index, sample in enumerate(samples):
            x, y, z, vm = sample
            writer.writerow([index, index / float(sample_rate_hz), x, y, z, vm])


def write_rr_csv(path, intervals_ms):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rr_index", "rr_interval_ms"])
        for index, value in enumerate(intervals_ms):
            writer.writerow([index, value])


def save_session(
    output_root,
    person_id,
    state,
    session_id,
    duration_seconds,
    collection,
    acc_sample_rate_hz=DEFAULT_ACC_SAMPLE_RATE_HZ,
    acc_range_g=DEFAULT_ACC_RANGE_G,
):
    safe_person = _safe_name(person_id)
    safe_state = _safe_name(state.lower())
    session_dir = Path(output_root) / safe_person / safe_state / _safe_name(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    ecg_path = session_dir / "ecg.csv"
    acc_path = session_dir / "acc.csv"
    rr_path = session_dir / "rr.csv"
    metadata_path = session_dir / "metadata.json"

    write_ecg_csv(ecg_path, collection["ecg_samples"], REALTIME_ECG_SAMPLE_RATE_HZ)
    write_acc_csv(acc_path, collection["acc_samples"], acc_sample_rate_hz)
    write_rr_csv(rr_path, collection["rr_intervals_ms"])

    started_at = datetime.now().astimezone().isoformat()
    requested_duration = float(duration_seconds)
    expected_ecg_samples = max(1, int(requested_duration * REALTIME_ECG_SAMPLE_RATE_HZ))
    expected_acc_samples = max(1, int(requested_duration * int(acc_sample_rate_hz)))
    ecg_duration_seconds = len(collection["ecg_samples"]) / float(REALTIME_ECG_SAMPLE_RATE_HZ)
    acc_duration_seconds = len(collection["acc_samples"]) / float(acc_sample_rate_hz)
    ecg_sample_loss_ratio = max(0.0, 1.0 - (len(collection["ecg_samples"]) / expected_ecg_samples))
    acc_sample_loss_ratio = max(0.0, 1.0 - (len(collection["acc_samples"]) / expected_acc_samples))
    collection_quality = (
        "ok"
        if ecg_duration_seconds >= MIN_USABLE_SECONDS and acc_duration_seconds >= MIN_USABLE_SECONDS
        else "short"
    )
    metadata = {
        "person_id": person_id,
        "state": state.lower(),
        "session_id": session_id,
        "device": POLAR_DEVICE_NAME,
        "device_address": collection["address"],
        "created_at": started_at,
        "requested_duration_seconds": requested_duration,
        "warmup_allowance_seconds": WARMUP_ALLOWANCE_SECONDS,
        "minimum_recommended_usable_seconds": MIN_USABLE_SECONDS,
        "ecg_sample_rate_hz": REALTIME_ECG_SAMPLE_RATE_HZ,
        "acc_sample_rate_hz": int(acc_sample_rate_hz),
        "acc_range_g": int(acc_range_g),
        "ecg_sample_count": len(collection["ecg_samples"]),
        "acc_sample_count": len(collection["acc_samples"]),
        "rr_interval_count": len(collection["rr_intervals_ms"]),
        "ecg_duration_seconds": ecg_duration_seconds,
        "acc_duration_seconds": acc_duration_seconds,
        "ecg_effective_sample_rate_hz": len(collection["ecg_samples"]) / requested_duration,
        "acc_effective_sample_rate_hz": len(collection["acc_samples"]) / requested_duration,
        "expected_ecg_sample_count": expected_ecg_samples,
        "expected_acc_sample_count": expected_acc_samples,
        "ecg_sample_loss_ratio": ecg_sample_loss_ratio,
        "acc_sample_loss_ratio": acc_sample_loss_ratio,
        "usable_window_count_30s": int(ecg_duration_seconds // 30),
        "collection_quality": collection_quality,
        "files": {
            "ecg": str(ecg_path),
            "acc": str(acc_path),
            "rr": str(rr_path),
        },
        "stats": collection["stats"],
        "notes": [
            "Use rest/walk/active as activity labels for evaluation, not as medical labels.",
            "ACC should be collected with ECG to support activity context and reduce false alerts.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return session_dir, metadata


def parse_args():
    parser = argparse.ArgumentParser(description="Collect real Polar H10 ECG/ACC data for model evaluation.")
    parser.add_argument("--person-id", required=True, help="Person folder name, e.g. person_01 or chinh.")
    parser.add_argument("--state", required=True, choices=sorted(VALID_STATES), help="Collection state label.")
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=DEFAULT_COLLECTION_SECONDS,
        help="Collection duration. Default: 330s to allow about 30s BLE warmup and retain ~300s usable data.",
    )
    parser.add_argument("--address", default=None, help="Polar H10 BLE address. If omitted, scan for Polar H10.")
    parser.add_argument("--scan-timeout", type=float, default=20, help="BLE scan timeout in seconds.")
    parser.add_argument("--output-root", default="data_raw/real_data", help="Root folder for real data.")
    parser.add_argument("--session-id", default=None, help="Optional session id. Default: session_YYYYMMDD_HHMMSS.")
    parser.add_argument(
        "--acc-sample-rate-hz",
        type=int,
        choices=SUPPORTED_ACC_SAMPLE_RATES_HZ,
        default=DEFAULT_ACC_SAMPLE_RATE_HZ,
        help="Polar H10 ACC sample rate. Default: 50Hz.",
    )
    parser.add_argument(
        "--acc-range-g",
        type=int,
        choices=SUPPORTED_ACC_RANGES_G,
        default=DEFAULT_ACC_RANGE_G,
        help="Polar H10 ACC range. Default: 8G.",
    )
    return parser.parse_args()


async def async_main():
    args = parse_args()
    session_id = args.session_id or f"session_{_session_timestamp()}"
    collection = await collect_polar_session(
        address=args.address,
        duration_seconds=args.duration_seconds,
        scan_timeout=args.scan_timeout,
        acc_sample_rate_hz=args.acc_sample_rate_hz,
        acc_range_g=args.acc_range_g,
    )
    session_dir, metadata = save_session(
        output_root=args.output_root,
        person_id=args.person_id,
        state=args.state,
        session_id=session_id,
        duration_seconds=args.duration_seconds,
        collection=collection,
        acc_sample_rate_hz=args.acc_sample_rate_hz,
        acc_range_g=args.acc_range_g,
    )
    print(f"Saved real-data session: {session_dir}")
    print(
        "Samples: "
        f"ECG={metadata['ecg_sample_count']} "
        f"ACC={metadata['acc_sample_count']} "
        f"RR={metadata['rr_interval_count']}"
    )
    if metadata["ecg_sample_count"] == 0:
        print("Warning: no ECG samples were collected.")
    if metadata["acc_sample_count"] == 0:
        print("Warning: no ACC samples were collected. Activity-context evaluation will be limited.")
    if metadata["collection_quality"] != "ok":
        print(
            "Warning: usable data is shorter than recommended. "
            f"ECG={metadata['ecg_duration_seconds']:.1f}s, "
            f"ACC={metadata['acc_duration_seconds']:.1f}s. "
            f"Recommended usable duration is {MIN_USABLE_SECONDS}s."
        )
    print(
        "Sample loss estimate: "
        f"ECG={metadata['ecg_sample_loss_ratio']:.1%}, "
        f"ACC={metadata['acc_sample_loss_ratio']:.1%}"
    )


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Collection stopped by user before the session could be saved.")


if __name__ == "__main__":
    main()
