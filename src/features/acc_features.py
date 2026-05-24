import struct

import numpy as np

from src.config.runtime_config import get_config_section


TYPE_ACC = 0x02
FS_ACC_HZ = 25

ACTIVITY_HR_THRESHOLDS = {
    "REST": (45, 90, 100, 130),
    "SLOW_WALK": (48, 105, 115, 140),
    "WALK": (50, 120, 130, 150),
    "ACTIVE": (55, 135, 145, 160),
    "UNKNOWN": (45, 100, 110, 135),
}

ACC_VM_STD_THRESHOLDS = {
    20: "REST",
    80: "SLOW_WALK",
    300: "WALK",
}

FALL_IMPACT_THRESHOLD_MG = 2000
FALL_FREE_FALL_THRESHOLD_MG = 500
FALL_POST_STILL_STD_MG = 120
FALL_PROX_S = 1.0
FALL_STRONG_IMPACT_MG = 2800
FALL_POST_STILL_SECONDS = 3
FALL_MIN_POST_STILL_SECONDS = 2


def parse_acc_packet(data: bytes) -> tuple[int, list[tuple[float, float, float, float]]]:
    """Parse Polar PMD ACC packet into (timestamp_ns, [(x, y, z, vm), ...])."""
    if len(data) < 10 or (data[0] & 0x3F) != TYPE_ACC:
        return 0, []

    timestamp_ns = struct.unpack_from("<Q", data, 1)[0]
    frame_type = data[9] & 0x7F
    is_compressed = bool(data[9] & 0x80)
    if is_compressed or frame_type not in (0, 1, 2):
        return timestamp_ns, []

    sample_size = {0: 1, 1: 2, 2: 3}[frame_type]
    sample_bytes = sample_size * 3
    samples = []
    offset = 10
    while offset + sample_bytes <= len(data):
        if sample_size == 1:
            x, y, z = struct.unpack_from("<bbb", data, offset)
        elif sample_size == 2:
            x, y, z = struct.unpack_from("<hhh", data, offset)
        else:
            x = int.from_bytes(data[offset : offset + 3], "little", signed=True)
            y = int.from_bytes(data[offset + 3 : offset + 6], "little", signed=True)
            z = int.from_bytes(data[offset + 6 : offset + 9], "little", signed=True)
        vm = float(np.sqrt(x * x + y * y + z * z))
        samples.append((float(x), float(y), float(z), vm))
        offset += sample_bytes

    return timestamp_ns, samples


def normalize_acc_samples(acc_samples) -> np.ndarray:
    """Return Nx4 array with columns x_mg, y_mg, z_mg, vm_mg."""
    if acc_samples is None:
        return np.empty((0, 4), dtype=float)

    rows = []
    for item in acc_samples:
        if isinstance(item, dict):
            x = item.get("x_mg", item.get("x", item.get("acc_x_mg")))
            y = item.get("y_mg", item.get("y", item.get("acc_y_mg")))
            z = item.get("z_mg", item.get("z", item.get("acc_z_mg")))
            vm = item.get("vm_mg", item.get("vm"))
        else:
            values = list(item)
            if len(values) < 3:
                continue
            x, y, z = values[:3]
            vm = values[3] if len(values) >= 4 else None

        if x is None or y is None or z is None:
            continue
        x = float(x)
        y = float(y)
        z = float(z)
        vm = float(vm) if vm is not None else float(np.sqrt(x * x + y * y + z * z))
        rows.append((x, y, z, vm))

    if not rows:
        return np.empty((0, 4), dtype=float)
    return np.asarray(rows, dtype=float).reshape(-1, 4)


def _activity_vm_std_thresholds():
    config = get_config_section("activity")
    configured = config.get("vm_std_thresholds_mg") if config else None
    if not configured:
        return dict(ACC_VM_STD_THRESHOLDS)
    thresholds = {}
    for threshold, label in configured.items():
        thresholds[float(threshold)] = str(label)
    return thresholds


def _fall_thresholds():
    config = get_config_section("fall")
    return {
        "impact_threshold_mg": float(config.get("impact_threshold_mg", FALL_IMPACT_THRESHOLD_MG)),
        "free_fall_threshold_mg": float(config.get("free_fall_threshold_mg", FALL_FREE_FALL_THRESHOLD_MG)),
        "post_still_std_mg": float(config.get("post_still_std_mg", FALL_POST_STILL_STD_MG)),
        "prox_s": float(config.get("prox_s", FALL_PROX_S)),
        "strong_impact_mg": float(config.get("strong_impact_mg", FALL_STRONG_IMPACT_MG)),
        "post_still_seconds": float(config.get("post_still_seconds", FALL_POST_STILL_SECONDS)),
        "min_post_still_seconds": float(
            config.get("min_post_still_seconds", FALL_MIN_POST_STILL_SECONDS)
        ),
        "active_fall_candidate_min_impact_mg": float(
            config.get("active_fall_candidate_min_impact_mg", FALL_STRONG_IMPACT_MG)
        ),
    }


def classify_activity(vm_std: float) -> str:
    for threshold, label in sorted(_activity_vm_std_thresholds().items()):
        if float(vm_std) < threshold:
            return label
    return "ACTIVE"


def detect_fall(vm_array, sample_rate_hz: int = FS_ACC_HZ, activity_state=None) -> dict:
    vm = np.asarray(vm_array, dtype=float).flatten()
    thresholds = _fall_thresholds()
    result = {
        "impact_spike": False,
        "free_fall": False,
        "post_still": False,
        "fall_candidate": False,
        "strong_fall": False,
        "impact_only": False,
        "confidence": 0.0,
        "reason": "",
        "peak_vm": 0.0,
        "min_before_1s": 0.0,
        "std_after_5s": 0.0,
        "n_impacts": 0,
        "fall_offset_s": -1.0,
    }
    if vm.size < sample_rate_hz * 3:
        return result

    peaks = []
    min_distance = max(1, int(sample_rate_hz * 0.6))
    last_peak = -min_distance
    for i in range(1, vm.size - 1):
        if vm[i] < thresholds["impact_threshold_mg"]:
            continue
        if vm[i] < vm[i - 1] or vm[i] < vm[i + 1]:
            continue
        if i - last_peak < min_distance:
            if peaks and vm[i] > vm[peaks[-1]]:
                peaks[-1] = i
                last_peak = i
            continue
        peaks.append(i)
        last_peak = i

    result["n_impacts"] = int(len(peaks))
    if not peaks:
        return result

    prox = max(1, int(sample_rate_hz * thresholds["prox_s"]))
    after_n = int(sample_rate_hz * thresholds["post_still_seconds"])
    min_after = int(sample_rate_hz * thresholds["min_post_still_seconds"])
    best_score = -1
    best = None

    for peak_idx in peaks:
        before = vm[max(0, peak_idx - prox) : peak_idx]
        if before.size == 0:
            continue
        min_before = float(np.min(before))
        free_fall = min_before < thresholds["free_fall_threshold_mg"]

        after = vm[peak_idx + 1 : peak_idx + 1 + after_n]
        post_still = False
        std_after = 0.0
        if after.size >= min_after:
            std_after = float(np.std(after))
            post_still = std_after < thresholds["post_still_std_mg"]

        score = (2 if free_fall else 0) + (2 if post_still else 0)
        if score > best_score or (score == best_score and (best is None or vm[peak_idx] > vm[best[0]])):
            best_score = score
            best = (int(peak_idx), free_fall, post_still, min_before, std_after)

    if best is None:
        return result

    peak_idx, free_fall, post_still, min_before, std_after = best
    peak_vm = float(vm[peak_idx])
    impact_only = not (free_fall and post_still)
    fall_candidate = bool(free_fall and post_still)
    active_suppressed = False
    if (
        str(activity_state or "").upper() == "ACTIVE"
        and fall_candidate
        and peak_vm < thresholds["active_fall_candidate_min_impact_mg"]
    ):
        fall_candidate = False
        impact_only = True
        active_suppressed = True
    strong_fall = bool(fall_candidate and peak_vm >= thresholds["strong_impact_mg"])
    confidence = 0.0
    if fall_candidate:
        confidence = 0.75
        if strong_fall:
            confidence = 0.95
    elif free_fall or post_still:
        confidence = 0.35

    if strong_fall:
        reason = "impact + free-fall + post-still"
    elif fall_candidate:
        reason = "fall candidate: free-fall followed by post-still"
    elif free_fall and not post_still:
        reason = "impact with free-fall but no post-still; treated as motion/impact only"
    elif post_still and not free_fall:
        reason = "impact with post-still but no free-fall; treated as low-confidence impact"
    elif active_suppressed:
        reason = "active-motion impact below calibrated active fall threshold"
    else:
        reason = "impact spike only"

    result.update(
        {
            "impact_spike": True,
            "free_fall": bool(free_fall),
            "post_still": bool(post_still),
            "fall_candidate": fall_candidate,
            "strong_fall": strong_fall,
            "impact_only": impact_only,
            "confidence": round(confidence, 3),
            "reason": reason,
            "peak_vm": round(peak_vm, 2),
            "min_before_1s": round(min_before, 2),
            "std_after_5s": round(std_after, 2),
            "fall_offset_s": round(peak_idx / float(sample_rate_hz), 2),
            "activity_state": activity_state,
            "calibrated_thresholds": {
                "impact_threshold_mg": thresholds["impact_threshold_mg"],
                "active_fall_candidate_min_impact_mg": thresholds["active_fall_candidate_min_impact_mg"],
                "strong_impact_mg": thresholds["strong_impact_mg"],
            },
        }
    )
    return result


def context_hr_alert(heart_rate_bpm, activity: str) -> dict:
    if heart_rate_bpm is None:
        return {"level": "SAFE", "reason": "", "threshold_bpm": None}

    hr = float(heart_rate_bpm)
    low, high_watch, high_alert, high_critical = ACTIVITY_HR_THRESHOLDS.get(
        activity, ACTIVITY_HR_THRESHOLDS["UNKNOWN"]
    )
    if hr >= high_critical:
        return {
            "level": "CRITICAL",
            "reason": f"HR={hr:.0f} dangerous for {activity} (>{high_critical})",
            "threshold_bpm": high_critical,
        }
    if hr >= high_alert:
        return {
            "level": "ALERT",
            "reason": f"HR={hr:.0f} unusually high for {activity} (>{high_alert})",
            "threshold_bpm": high_alert,
        }
    if hr >= high_watch:
        return {
            "level": "WATCH",
            "reason": f"HR={hr:.0f} elevated for {activity} (>{high_watch})",
            "threshold_bpm": high_watch,
        }
    if hr < low:
        return {
            "level": "ALERT",
            "reason": f"HR={hr:.0f} unusually low for {activity} (<{low})",
            "threshold_bpm": low,
        }
    return {"level": "SAFE", "reason": "", "threshold_bpm": high_alert}


def summarize_acc_window(acc_samples, heart_rate_bpm=None, sample_rate_hz: int = FS_ACC_HZ) -> dict:
    acc = normalize_acc_samples(acc_samples)
    if acc.size == 0:
        return {}

    xs = acc[:, 0]
    ys = acc[:, 1]
    zs = acc[:, 2]
    vm = acc[:, 3]
    vm_std = float(np.std(vm))
    vm_mean = float(np.mean(vm))
    vm_max = float(np.max(vm))
    activity = classify_activity(vm_std)
    fall = detect_fall(vm, sample_rate_hz=sample_rate_hz, activity_state=activity)
    hr_context = context_hr_alert(heart_rate_bpm, activity)

    return {
        "activity_state": activity,
        "activity_features": {
            "sample_count": int(acc.shape[0]),
            "sample_rate_hz": float(sample_rate_hz),
            "acc_vm_mean": round(vm_mean, 2),
            "acc_vm_std": round(vm_std, 2),
            "acc_vm_max": round(vm_max, 2),
            "acc_vm_range": round(vm_max - float(np.min(vm)), 2),
            "acc_x_std": round(float(np.std(xs)), 2),
            "acc_y_std": round(float(np.std(ys)), 2),
            "acc_z_std": round(float(np.std(zs)), 2),
            "acc_energy": round(float(np.mean(vm**2)), 2),
        },
        "fall": fall,
        "hr_context_alert": hr_context,
    }
