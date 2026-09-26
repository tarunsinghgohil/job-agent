setup:
	cp -n .env.example .env || true

dev:
	docker compose up --build

stop:
	docker compose down
