import asyncio
import httpx
import time
import argparse
from typing import List, Dict

from common.cluster import create_simulated_cluster

async def worker(client: httpx.AsyncClient, num_requests: int, results: List[Dict]):
    for i in range(num_requests):
        task_payload = {
            "workload_type": "inference",
            "model_id": "vision-classifier-v3",
            "sla_class": "real_time",
            "payload_ref": "s3://test/data",
            "idempotency_key": f"load-test-{time.time()}-{i}",
        }
        
        start = time.perf_counter()
        resp = await client.post("/v1/tasks/infer", json=task_payload)
        end = time.perf_counter()
        
        if resp.status_code == 200:
            data = resp.json()
            results.append({
                "e2e_latency_ms": (end - start) * 1000.0,
                "decision_latency_ms": data["execution_metadata"]["decision_overhead_ms"],
                "execution_latency_ms": data["execution_metadata"]["execution_time_ms"],
                "node": data["execution_metadata"]["executed_node"],
                "status": "success"
            })
        else:
            results.append({
                "e2e_latency_ms": (end - start) * 1000.0,
                "status": "error"
            })

async def run_load_test(concurrency: int, total_requests: int):
    print(f"==================================================")
    print(f" INITIALIZING LOAD TEST: {total_requests} reqs, c={concurrency}")
    print(f"==================================================")
    
    telemetry_store, decision_engine, scheduler, aggregator, nodes, app, grpc_servers = create_simulated_cluster()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    
    results = []
    reqs_per_worker = total_requests // concurrency
    
    print(f"Blasting API with {total_requests} requests...")
    start_time = time.perf_counter()
    
    tasks = [worker(client, reqs_per_worker, results) for _ in range(concurrency)]
    await asyncio.gather(*tasks)
    
    end_time = time.perf_counter()
    total_time = end_time - start_time
    
    await client.aclose()
    for srv in grpc_servers:
        srv.stop(0)
        
    # Analyze
    successes = [r for r in results if r["status"] == "success"]
    errors = [r for r in results if r["status"] == "error"]
    
    print("\n==================================================")
    print(" LOAD TEST REPORT")
    print("==================================================")
    print(f"Total Requests:      {len(results)}")
    print(f"Concurrency:         {concurrency}")
    print(f"Total Time:          {total_time:.2f} s")
    print(f"Throughput (RPS):    {len(results) / total_time:.2f} req/s")
    print(f"Success Rate:        {len(successes)/len(results)*100:.2f}% ({len(errors)} errors)")
    
    def p(data, perc):
        if not data: return 0.0
        data = sorted(data)
        idx = int(len(data) * perc / 100.0)
        return data[min(idx, len(data)-1)]
        
    if successes:
        e2e_lats = [r["e2e_latency_ms"] for r in successes]
        dec_lats = [r["decision_latency_ms"] for r in successes]
        
        print("\nLatency Breakdown (ms):")
        print("Metric               |   p50   |   p95   |   p99   |   max")
        print("---------------------|---------|---------|---------|---------")
        print(f"Decision Engine      | {p(dec_lats, 50):7.2f} | {p(dec_lats, 95):7.2f} | {p(dec_lats, 99):7.2f} | {max(dec_lats):7.2f}")
        print(f"End-to-End Latency   | {p(e2e_lats, 50):7.2f} | {p(e2e_lats, 95):7.2f} | {p(e2e_lats, 99):7.2f} | {max(e2e_lats):7.2f}")
        
        print("\nPlacement Distribution:")
        nodes_dist = {}
        for r in successes:
            nodes_dist[r["node"]] = nodes_dist.get(r["node"], 0) + 1
        for n, count in nodes_dist.items():
            print(f"  {n:<20} {count} ({count/len(successes)*100:.1f}%)")
            
        print("\nTarget Verification:")
        p99_dec = p(dec_lats, 99)
        if p99_dec < 10.0:
            print(f"[PASSED] p99 Decision Latency is < 10ms ({p99_dec:.2f}ms)")
        else:
            print(f"[FAILED] p99 Decision Latency exceeded 10ms ({p99_dec:.2f}ms)")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Orchestration Load Tester")
    parser.add_argument("-n", "--requests", type=int, default=1000, help="Total requests")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="Concurrent workers")
    args = parser.parse_args()
    
    asyncio.run(run_load_test(args.concurrency, args.requests))
