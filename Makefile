.PHONY: run test redis
run:          ## run the full analysis (needs Redis at $REDIS_URL)
	python main.py
test:         ## run the test suite (needs Redis; skips cleanly without it)
	python -m pytest -q
redis:        ## start a local Redis in Docker
	docker run --name my-redis -p 6379:6379 -d redis
