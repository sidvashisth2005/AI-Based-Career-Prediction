"""Train (or retrain) the career prediction model and print evaluation metrics.

Usage: python -m scripts.train_model [--samples 400] [--seed 42]
"""

import argparse
import json

from app import predictor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=400, help="synthetic profiles per career")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    bundle = predictor.train(samples_per_career=args.samples, seed=args.seed)
    print(json.dumps(bundle["metrics"], indent=2))
    print(f"Saved model to {predictor.MODEL_PATH}")


if __name__ == "__main__":
    main()
