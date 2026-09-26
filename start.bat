@echo off
copy /Y .env.example .env >nul
 docker compose up --build
