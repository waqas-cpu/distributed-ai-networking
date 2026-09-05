import httpx
import argparse
import sys
import json

def inspect_task(gateway_url: str, task_id: str):
    print(f"Fetching audit record for Task: {task_id}")
    try:
        resp = httpx.get(f"{gateway_url}/v1/audit/events?task_id={task_id}")
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        print(f"Failed to fetch audit events: {e}")
        sys.exit(1)

    if not events:
        print("No audit events found for this task.")
        sys.exit(1)

    event = events[-1] # most recent event
    decision = event.get("decision", {})
    execution = event.get("execution", {})

    print("="*60)
    print("  PLACEMENT DECISION INSPECTOR")
    print("="*60)
    print(f"Task:              {event['task_id']}")
    print(f"Timestamp:         {event['timestamp']}")
    print(f"SLA Class:         {decision.get('weights_used', {}).get('name', 'N/A')}")
    print(f"Selected:          {decision.get('chosen_node')}")
    print(f"Decision latency:  {decision.get('decision_latency_ms', 0):.2f} ms")
    
    print("\nScore breakdown (Weights used):")
    weights = decision.get("weights_used", {})
    for k, v in weights.items():
        if k != "name":
            print(f"  {k:<12} {v:.2f}")

    print("\nCandidates:")
    # We only log the chosen and runner-up in the audit currently
    print(f"  {decision.get('chosen_node'):<15} {decision.get('chosen_score', 0.0):.4f}   SELECTED")
    if decision.get("runner_up_node"):
        print(f"  {decision.get('runner_up_node'):<15} {decision.get('runner_up_score', 0.0):.4f}")

    print("\nFallback chain:")
    chain = decision.get("fallback_chain", [])
    print("  " + " -> ".join(chain))

    print("\nStatus:")
    print(f"  {execution.get('status')}")
    if event.get("fallback_activated"):
        print(f"  (Fallback activated, completed on attempt {event.get('attempts')})")
    
    if decision.get("filtered_out_nodes"):
        print("\nExcluded Candidates:")
        for k, v in decision.get("filtered_out_nodes").items():
            print(f"  {k:<15} Reason: {v}")
            
    print("="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Placement Decision Inspector")
    parser.add_argument("task_id", help="The Task ID to inspect")
    parser.add_argument("--url", default="http://localhost:8000", help="Gateway URL")
    args = parser.parse_args()

    inspect_task(args.url, args.task_id)
