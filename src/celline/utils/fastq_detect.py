#!/usr/bin/env python3
"""
Auto-detect R1/R2 orientation for 10x scRNA-seq data.

This module analyzes FASTQ files to determine which is R1 (barcode+UMI)
and which is R2 (cDNA) based on read length and poly(A/T) patterns.

Strategy:
1. Read length heuristic: R1 is typically 24-30bp (CB+UMI), R2 is 50-150bp (cDNA)
2. Poly(A/T) signature: R2 (cDNA) often has poly(A/T) stretches at the beginning
"""

import gzip
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# Constants
POLY_REGEX = re.compile(r"(A{8,}|T{8,})")  # 8+ consecutive A or T
SAMPLE_READS = 100000  # Number of reads to sample for detection
R1_LEN_WINDOW = (24, 30)  # Expected R1 length range (CB+UMI)
R2_MIN_LEN = 50  # Minimum expected R2 length


def open_fastq(path: Path):
    """Open FASTQ file (gzipped or plain text)."""
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt")
    return open(path, "rt", encoding="utf-8", errors="ignore")


def fastq_iter_seqs(path: Path, max_reads: int = SAMPLE_READS):
    """Iterate over sequences in FASTQ file."""
    n = 0
    with open_fastq(path) as fh:
        while True:
            header = fh.readline()
            if not header:
                break
            seq = fh.readline().strip()
            fh.readline()  # +
            fh.readline()  # quality
            if not seq:
                break
            yield seq
            n += 1
            if max_reads and n >= max_reads:
                break


def gather_stats(path: Path) -> Dict:
    """Gather statistics from FASTQ file.

    Returns:
        dict with:
            - total: number of reads analyzed
            - mode_len: most common read length
            - poly_frac: fraction of reads with poly(A/T) in first 30bp
            - lengths: Counter of all lengths
    """
    lengths = Counter()
    poly_hits = 0
    total = 0

    for seq in fastq_iter_seqs(path):
        total += 1
        lengths[len(seq)] += 1
        # Check for poly(A/T) in first 30bp
        if POLY_REGEX.search(seq[:30]):
            poly_hits += 1

    if not lengths:
        raise ValueError(f"No reads found in {path}")

    mode_len, _ = max(lengths.items(), key=lambda x: x[1])
    poly_frac = (poly_hits / total) if total else 0.0

    return {
        "total": total,
        "mode_len": mode_len,
        "poly_frac": poly_frac,
        "lengths": lengths
    }


def score_as_r1(stat: Dict) -> int:
    """Score how likely this file is R1 (barcode+UMI).

    Higher score = more likely to be R1
    """
    score = 0

    # Strong evidence: length in R1 range
    if R1_LEN_WINDOW[0] <= stat["mode_len"] <= R1_LEN_WINDOW[1]:
        score += 3

    # Moderate evidence: short reads
    if stat["mode_len"] <= 40:
        score += 1

    # R1 should have low poly(A/T) content
    if stat["poly_frac"] < 0.10:
        score += 1

    # Very short reads (< 24bp) - could be trimmed R1 or index reads
    # Note: This function is only used for 2-file scenarios (R1/R2),
    # so index reads (I1/I2) should not appear here
    if stat["mode_len"] < R1_LEN_WINDOW[0]:
        score += 2

    return score


def detect_r1_r2(file1: Path, file2: Path) -> Dict:
    """Detect which file is R1 and which is R2.

    Args:
        file1: Path to first FASTQ file
        file2: Path to second FASTQ file

    Returns:
        dict with:
            - R1: Path to R1 file
            - R2: Path to R2 file
            - stats: statistics for both files
            - scores: R1 scores for both files
            - confidence: "high", "medium", or "low"
    """
    logger.info(f"Analyzing {file1.name} and {file2.name}...")

    # Gather statistics
    stats1 = gather_stats(file1)
    stats2 = gather_stats(file2)

    # Score each file
    score1 = score_as_r1(stats1)
    score2 = score_as_r1(stats2)

    logger.info(f"{file1.name}: len={stats1['mode_len']}, polyAT={stats1['poly_frac']:.3f}, score={score1}")
    logger.info(f"{file2.name}: len={stats2['mode_len']}, polyAT={stats2['poly_frac']:.3f}, score={score2}")

    # Determine R1/R2
    if score1 == score2:
        # Tie-breaker: shorter is R1
        r1_file = file1 if stats1["mode_len"] <= stats2["mode_len"] else file2
    else:
        r1_file = file1 if score1 > score2 else file2

    r2_file = file2 if r1_file == file1 else file1

    # Determine confidence
    score_delta = abs(score1 - score2)
    if score_delta == 0:
        confidence = "low"
    elif score_delta == 1:
        confidence = "medium"
    else:
        confidence = "high"

    result = {
        "R1": r1_file,
        "R2": r2_file,
        "stats": {file1: stats1, file2: stats2},
        "scores": {file1: score1, file2: score2},
        "confidence": confidence
    }

    logger.info(f"Result: R1={r1_file.name}, R2={r2_file.name} (confidence: {confidence})")

    return result


def rename_to_10x_format(
    file1: Path,
    file2: Path,
    sample_id: str,
    lane: str = "L001",
    part: str = "001",
    dry_run: bool = False
) -> Tuple[Path, Path]:
    """Detect R1/R2 and rename to 10x format.

    Args:
        file1: First FASTQ file
        file2: Second FASTQ file
        sample_id: Sample ID for output naming
        lane: Lane identifier (default: L001)
        part: Part identifier (default: 001)
        dry_run: If True, only print what would be done

    Returns:
        Tuple of (R1_path, R2_path) after renaming
    """
    # Detect R1/R2
    result = detect_r1_r2(file1, file2)

    r1_file = result["R1"]
    r2_file = result["R2"]

    # Generate 10x-style names
    gz_ext = ".gz" if str(r1_file).endswith(".gz") else ""
    r1_new = r1_file.parent / f"{sample_id}_S1_{lane}_R1_{part}.fastq{gz_ext}"
    r2_new = r2_file.parent / f"{sample_id}_S1_{lane}_R2_{part}.fastq{gz_ext}"

    if dry_run:
        logger.info(f"[DRY RUN] Would rename:")
        logger.info(f"  {r1_file.name} -> {r1_new.name}")
        logger.info(f"  {r2_file.name} -> {r2_new.name}")
        return r1_new, r2_new

    # Check for conflicts
    if r1_new.exists() or r2_new.exists():
        raise FileExistsError(f"Output files already exist: {r1_new} or {r2_new}")

    # Rename
    r1_file.rename(r1_new)
    r2_file.rename(r2_new)

    logger.info(f"Renamed: {r1_file.name} -> {r1_new.name}")
    logger.info(f"Renamed: {r2_file.name} -> {r2_new.name}")

    return r1_new, r2_new


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect 10x R1/R2 orientation and optionally rename files"
    )
    parser.add_argument("fastq1", type=Path, help="First FASTQ file")
    parser.add_argument("fastq2", type=Path, help="Second FASTQ file")
    parser.add_argument("--sample", help="Sample ID for renaming")
    parser.add_argument("--lane", default="L001", help="Lane ID (default: L001)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s"
    )

    if args.sample:
        # Rename mode
        rename_to_10x_format(
            args.fastq1,
            args.fastq2,
            args.sample,
            lane=args.lane,
            dry_run=args.dry_run
        )
    else:
        # Detection only mode
        result = detect_r1_r2(args.fastq1, args.fastq2)
        print(f"\nR1: {result['R1'].name}")
        print(f"R2: {result['R2'].name}")
        print(f"Confidence: {result['confidence']}")


if __name__ == "__main__":
    main()
