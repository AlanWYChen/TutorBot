MODEL_COMPOSE = $(COMPOSE) -f infra/compose/model-contracts.yaml --profile model-checks
COMPOSE = docker compose --env-file .env -f infra/compose/compose.yaml
.PHONY: setup up down status check smoke seed-auth auth-integration model-integration private-io-integration upload-integration viewer-integration studio-integration dataset-integration seed-dataset
setup:
	@test -f .env || cp .env.example .env
up:
	$(COMPOSE) up --build -d --wait --wait-timeout 300
down:
	$(COMPOSE) down
status:
	$(COMPOSE) ps
check:
	npm ci
	npm run lint
	npm run typecheck
	npm test
	docker build -f apps/api/Dockerfile --target checks -t tutorbot-api-checks .
	docker run --rm tutorbot-api-checks sh -c "ruff check . /workspace/infra/litellm/render_config.py && mypy app && pytest"
smoke:
	python3 scripts/smoke.py

seed-auth:
	$(COMPOSE) exec -T admin-api python -m scripts.seed_local_auth

auth-integration:
	$(COMPOSE) run --rm --no-deps --build -e RUN_AUTH_INTEGRATION=1 api-checks pytest tests/test_auth_integration.py tests/test_migration_integration.py tests/test_service_security_integration.py

model-integration:
	@trap '$(MODEL_COMPOSE) stop model-openai model-deepseek model-fixture' EXIT; \
	$(MODEL_COMPOSE) up --build -d --wait --wait-timeout 300 model-fixture model-openai model-deepseek && \
	$(MODEL_COMPOSE) run --rm --no-deps --build -e RUN_MODEL_INTEGRATION=1 api-checks pytest tests/test_model_proxy_integration.py

private-io-integration:
	bash scripts/check_private_io.sh

upload-integration:
	$(COMPOSE) run --rm --no-deps --build -e RUN_UPLOAD_INTEGRATION=1 api-checks pytest tests/test_upload_integration.py

viewer-integration:
	$(COMPOSE) run --rm --no-deps --build -e RUN_VIEWER_INTEGRATION=1 api-checks pytest tests/test_viewer_integration.py

studio-integration:
	$(COMPOSE) run --rm --no-deps --build -e RUN_STUDIO_INTEGRATION=1 api-checks pytest tests/test_studio_integration.py

dataset-integration:
	$(COMPOSE) run --rm --no-deps --build -e RUN_DATASET_INTEGRATION=1 api-checks pytest tests/test_dataset_integration.py

seed-dataset:
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR)/docs/datasets/synthetic-v1:/output" admin-api python -m scripts.seed_annotation_dataset seed /output
