.PHONY: start test test-unit test-integration chaos-test load-test inspect demo

start:
	python server.py

demo:
	python run_demo.py

test: test-unit chaos-test

test-unit:
	pytest tests/test_contracts.py tests/test_decision_engine.py tests/test_scheduler.py

test-integration:
	pytest tests/test_end_to_end.py

chaos-test:
	pytest tests/test_chaos.py

load-test:
	python load_test.py --requests 1000 --concurrency 50

inspect:
	python inspector.py $(TASK)
