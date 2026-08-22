@echo off
REM Build and push Docker image for News Feed Manager (amd64)
REM Target platform: linux/amd64
REM Docker Hub user: apollon67

setlocal

REM Configuration
set DOCKER_USER=apollon67
set IMAGE_NAME=newsreader
set TAG=latest
set PLATFORM=linux/amd64

REM Get current directory
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..

echo ========================================
echo Building Docker Image for NFM
echo ========================================
echo.
echo Docker User: %DOCKER_USER%
echo Image Name:  %IMAGE_NAME%
echo Tag:         %TAG%
echo Platform:    %PLATFORM%
echo.

REM Change to project directory
cd /d "%PROJECT_DIR%"

echo ========================================
echo Step 1: Building Docker Image
echo ========================================
echo.

docker buildx build ^
    --platform %PLATFORM% ^
    --file docker\Dockerfile.amd64 ^
    --tag %DOCKER_USER%/%IMAGE_NAME%:%TAG% ^
    --tag %DOCKER_USER%/%IMAGE_NAME%:amd64 ^
    --load ^
    .

if errorlevel 1 (
    echo.
    echo ERROR: Docker build failed!
    exit /b 1
)

echo.
echo ========================================
echo Step 2: Logging in to Docker Hub
echo ========================================
echo.

docker login

if errorlevel 1 (
    echo.
    echo ERROR: Docker login failed!
    exit /b 1
)

echo.
echo ========================================
echo Step 3: Pushing Image to Docker Hub
echo ========================================
echo.

docker push %DOCKER_USER%/%IMAGE_NAME%:%TAG%

if errorlevel 1 (
    echo.
    echo ERROR: Failed to push image with tag '%TAG%'!
    exit /b 1
)

docker push %DOCKER_USER%/%IMAGE_NAME%:amd64

if errorlevel 1 (
    echo.
    echo ERROR: Failed to push image with tag 'amd64'!
    exit /b 1
)

echo.
echo ========================================
echo Build and Push Completed Successfully!
echo ========================================
echo.
echo Image: %DOCKER_USER%/%IMAGE_NAME%:%TAG%
echo Image: %DOCKER_USER%/%IMAGE_NAME%:amd64
echo.
echo To run the application:
echo   cd docker
echo   docker-compose -f docker-compose.amd64.yml up -d
echo.

endlocal
