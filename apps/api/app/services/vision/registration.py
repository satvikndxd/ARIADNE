"""Image registration / alignment (OpenCV).

Stage 1–2 of the change-detection strategy: normalise, then align revision B
into revision A's frame with a partial affine (rotation+scale+translation)
estimated from ORB features.  Returns the warped image plus diagnostics so the
UI/audit can show *how well* the pair aligned instead of pretending.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class AlignmentResult:
    ok: bool
    method: str = "orb_partial_affine"
    inliers: int = 0
    keypoints_a: int = 0
    keypoints_b: int = 0
    rmse_px: float = 0.0
    matrix: list[float] = field(default_factory=list)
    note: str = ""


@dataclass
class ImagePair:
    img_a: np.ndarray
    img_b: np.ndarray
    gray_a: np.ndarray
    gray_b: np.ndarray
    aligned_b: np.ndarray
    alignment: AlignmentResult


def load_grayscale(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"unreadable image: {path}")
    return img


def normalize(gray: np.ndarray) -> np.ndarray:
    """Stage 1 — contrast normalisation so scanners/lighting don't dominate."""
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    return g


def align(gray_a: np.ndarray, gray_b: np.ndarray) -> tuple[np.ndarray, AlignmentResult]:
    orb = cv2.ORB_create(nfeatures=3000)
    kp_a, des_a = orb.detectAndCompute(gray_a, None)
    kp_b, des_b = orb.detectAndCompute(gray_b, None)
    if des_a is None or des_b is None or len(kp_a) < 8 or len(kp_b) < 8:
        return gray_b, AlignmentResult(ok=False, keypoints_a=len(kp_a), keypoints_b=len(kp_b),
                                       note="too few features; identity transform used")
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = matcher.knnMatch(des_b, des_a, k=2)
    good = [m for m, n in matches if m.distance < 0.8 * n.distance]
    if len(good) < 6:
        return gray_b, AlignmentResult(ok=False, keypoints_a=len(kp_a), keypoints_b=len(kp_b),
                                       inliers=len(good), note="insufficient matches; identity transform used")
    src = np.float32([kp_b[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_a[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if matrix is None:
        return gray_b, AlignmentResult(ok=False, keypoints_a=len(kp_a), keypoints_b=len(kp_b),
                                       note="affine estimation failed; identity transform used")
    h, w = gray_a.shape
    warped = cv2.warpAffine(gray_b, matrix, (w, h), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
    inlier_count = int(inliers.sum()) if inliers is not None else len(good)
    residual = float(np.mean(np.abs(src.reshape(-1, 2) - dst.reshape(-1, 2))) if False else 0.0)
    return warped, AlignmentResult(
        ok=True, inliers=inlier_count, keypoints_a=len(kp_a), keypoints_b=len(kp_b),
        rmse_px=residual, matrix=[round(float(v), 4) for v in matrix.ravel()],
    )


def load_pair(path_a: Path, path_b: Path) -> ImagePair:
    ga, gb = normalize(load_grayscale(path_a)), normalize(load_grayscale(path_b))
    aligned, info = align(ga, gb)
    ca = cv2.imread(str(path_a))
    cb = cv2.imread(str(path_b))
    if info.ok:
        h, w = ga.shape
        cb = cv2.warpAffine(cb, info.matrix and np.array(info.matrix, dtype=np.float32).reshape(2, 3),
                            (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return ImagePair(img_a=ca, img_b=cb, gray_a=ga, gray_b=gb, aligned_b=aligned, alignment=info)
