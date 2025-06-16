@echo off

:: Create the main project directory
md "azure-xray-triage-system"
cd "azure-xray-triage-system"

:: Create .github directory and its subdirectory
md ".github\workflows"

:: Create .vscode directory and its file (optional)
md ".vscode"
type nul > ".vscode\settings.json"

:: Create data directory and its subdirectories
md "data\raw"
md "data\processed"
md "data\sample"

:: Create deployment directory and its subdirectories
md "deployment\arm_templates"
md "deployment\kubernetes"

:: Create docs directory
md "docs"

:: Create notebooks directory
md "notebooks"

:: Create src directory and its subdirectories and files
md "src\api\routers"
md "src\api\schemas"
type nul > "src\__init__.py"
type nul > "src\api\__init__.py"
type nul > "src\api\main.py"
md "src\data_ingestion"
md "src\model_training"
md "src\preprocessing"
md "src\utils"

:: Create tests directory
md "tests"

:: Create root files
type nul > ".dockerignore"
type nul > ".gitignore"
type nul > "Dockerfile"
type nul > "LICENSE"
type nul > "Makefile"
type nul > "README.md"
type nul > "requirements.txt"
type nul > "requirements-dev.txt"
type nul > "setup.py"

echo Folder structure created successfully!
cd ..