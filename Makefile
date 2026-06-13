.PHONY: dev build preview install update

dev: update ## Start Vite dev server
	npm run dev

build: ## Build for production (runs update first)
	npm run build

preview: ## Preview the production build locally
	npm run preview

install: ## Install JS dependencies
	npm install

update: ## Fetch latest WC results and regenerate stats.json
	cd backend && uv run wc2026brief
