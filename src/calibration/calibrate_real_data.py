import argparse
import json

from src.calibration.anomaly_calibration import train_calibration_from_real_data


def parse_args():
    parser = argparse.ArgumentParser(
        description="Calibrate patient-specific anomaly model from local real_data baseline sessions."
    )
    parser.add_argument("--person-id", required=True, help="Person folder name under data_raw/real_data.")
    parser.add_argument(
        "--patient-id",
        default=None,
        help="Calibration artifact patient id. Default: same as --person-id.",
    )
    parser.add_argument("--input-dir", default="data_raw/real_data", help="Root folder containing real data.")
    parser.add_argument(
        "--states",
        default="rest",
        help="Comma-separated states to use as normal baseline. Default: rest.",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.03,
        help="Expected outlier ratio inside the marked normal baseline. Default: 0.03.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    states = tuple(state.strip().lower() for state in args.states.split(",") if state.strip())
    metadata = train_calibration_from_real_data(
        patient_id=args.patient_id or args.person_id,
        input_dir=args.input_dir,
        states=states,
        contamination=args.contamination,
        real_data_person_id=args.person_id,
    )
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
