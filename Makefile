.PHONY: test cov drill report up down

test:
	pytest -q

cov:
	pytest --cov=goldguard --cov-branch --cov-report=term-missing

# Failure drills from Phase 4/5: kill-app, position mismatch, order loop, watchdog flatten.
drill:
	pytest -q tests/test_drills.py tests/test_watchdog.py

report:
	python -m goldguard.backtest.report

up:
	docker compose up -d

down:
	docker compose down
