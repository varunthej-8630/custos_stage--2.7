# benchmark_ai.py — Benchmarks Perception and Tracking latency
import time
import numpy as np
from engine.perception_engine import PerceptionEngine
from engine.tracking_engine import MultiObjectTracker
from engine.behavior_analyzer import BehaviorAnalyzer
from engine.risk_engine import RiskEngine

def run_benchmarks():
    print("=" * 60)
    print(" CUSTOS 2.6 AI VISION & BEHAVIOR BENCHMARK")
    print("=" * 60)

    perception = PerceptionEngine()
    tracker = MultiObjectTracker()
    behavior = BehaviorAnalyzer()
    risk = RiskEngine()

    dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    # Warmup
    for _ in range(5):
        perception.detect(dummy_frame)

    # 1. Perception Benchmark
    n_iters = 30
    latencies = []
    for _ in range(n_iters):
        t0 = time.perf_counter()
        dets = perception.detect(dummy_frame)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_det_ms = sum(latencies) / len(latencies)
    min_det_ms = min(latencies)
    max_det_ms = max(latencies)

    # 2. Tracking Benchmark
    track_latencies = []
    mock_dets = [{'bbox': [100, 100, 200, 300], 'confidence': 0.9, 'class_id': 0, 'class_name': 'person'}]
    for _ in range(n_iters):
        t0 = time.perf_counter()
        tracks = tracker.update(mock_dets)
        track_latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_trk_ms = sum(track_latencies) / len(track_latencies)

    # 3. Behavior + Risk Benchmark
    b_latencies = []
    context = {'zones': [[50, 50, 350, 350]], 'zone_types': ['HIGH']}
    for _ in range(n_iters):
        t0 = time.perf_counter()
        b_res = behavior.process(tracks, context)
        score, reasons, alert = risk.evaluate(tracks, b_res['validated'], context['zones'], context['zone_types'])
        b_latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_risk_ms = sum(b_latencies) / len(b_latencies)

    total_pipeline_ms = avg_det_ms + avg_trk_ms + avg_risk_ms
    effective_fps = 1000.0 / total_pipeline_ms if total_pipeline_ms > 0 else 0

    print(f"Perception (YOLOv8n 480p): Avg = {avg_det_ms:.2f} ms (Min = {min_det_ms:.2f} ms, Max = {max_det_ms:.2f} ms)")
    print(f"Tracking (MultiObjectTracker): Avg = {avg_trk_ms:.3f} ms")
    print(f"Behavior & Risk Engine:    Avg = {avg_risk_ms:.3f} ms")
    print(f"Total AI Latency:          {total_pipeline_ms:.2f} ms")
    print(f"Maximum AI Throughput:     {effective_fps:.1f} FPS (without frame skipping)")
    print(f"Effective Ingestion FPS:   {effective_fps * 2:.1f} FPS (with FRAME_SKIP = 2)")
    print("=" * 60)

if __name__ == '__main__':
    run_benchmarks()
